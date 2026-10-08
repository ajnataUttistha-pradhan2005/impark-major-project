import asyncio
from uuid import uuid4

from backend.agents.common.contracts import Agent
from backend.contracts.actions import Action, ActionName, AgentInvocation, Capability, RetryMetadata
from backend.contracts.agents import (
    Failure,
    FailureType,
    GraphAgentInput,
    GraphParameters,
    GraphQuery,
    ImageAgentInput,
    Observation,
    TextAgentInput,
)
from backend.orchestrator.actions import REGISTRY
from backend.orchestrator.recovery import can_retry, pending_failure
from backend.state.models import ConversationState


class ExecutionManager:
    def __init__(
        self,
        text: Agent[TextAgentInput],
        image: Agent[ImageAgentInput],
        graph: Agent[GraphAgentInput],
    ) -> None:
        self.text, self.image, self.graph = text, image, graph

    def invocation(self, state: ConversationState, action: Action) -> AgentInvocation:
        correlation = state.correlation.model_copy(deep=True)
        correlation.action_id = action.action_id
        correlation.agent_invocation_id = uuid4()
        correlation.iteration = state.iteration
        retry = RetryMetadata()
        if action.name == ActionName.RETRY_ACTION:
            failure = pending_failure(state)
            if failure is None or not can_retry(state, failure):
                raise ValueError("Retry is not eligible")
            original = failure.invocation.action
            action = Action(name=original.name, retry_of=original.action_id)
            correlation.action_id = action.action_id
            count = state.execution.retry_counts.get(action.name, 0) + 1
            state.execution.retry_counts[action.name] = count
            state.execution.handled_failures.append(failure.failure_id)
            retry = RetryMetadata(attempt=count, original_action_id=original.action_id)
        state.correlation = correlation
        return AgentInvocation(
            correlation=correlation,
            action=action,
            capability=REGISTRY[action.name].capability,
            retry=retry,
        )

    async def execute(
        self, state: ConversationState, invocation: AgentInvocation
    ) -> Observation | Failure:
        try:
            async with asyncio.timeout(state.budgets.action_timeout_seconds):
                result = await self._invoke(state, invocation)
            # Reject forged lineage/provider contract mismatch at the capability boundary.
            if result.invocation != invocation:
                return self._failure(invocation, FailureType.PERMANENT, "Invalid result lineage")
            if isinstance(result, Observation) and result.component != invocation.capability:
                return self._failure(invocation, FailureType.PERMANENT, "Invalid result capability")
            return result
        except TimeoutError:
            return self._failure(invocation, FailureType.TIMEOUT, "Capability timed out", True)
        except Exception:
            # This top-level capability boundary deliberately redacts provider exception details.
            return self._failure(invocation, FailureType.PERMANENT, "Capability execution failed")

    async def _invoke(
        self, state: ConversationState, invocation: AgentInvocation
    ) -> Observation | Failure:
        if invocation.capability == Capability.TEXT:
            return await self.text.execute(
                TextAgentInput(
                    invocation=invocation,
                    text=state.user_message,
                    active_plant_id=(
                        state.context.active_plant.plant_id if state.context.active_plant else None
                    ),
                    reassessment=invocation.action.name == ActionName.REASSESS_ENTITY,
                )
            )
        if invocation.capability == Capability.IMAGE and state.image is not None:
            return await self.image.execute(
                ImageAgentInput(invocation=invocation, image=state.image)
            )
        if invocation.capability == Capability.GRAPH and state.context.active_plant is not None:
            objective = next(o for o in state.goal.pending if o.query_type is not None)
            assert objective.query_type is not None
            return await self.graph.execute(
                GraphAgentInput(
                    invocation=invocation,
                    objective_ids=[objective.objective_id],
                    evidence_gaps=state.evidence.gaps,
                    query=GraphQuery(
                        query_type=objective.query_type,
                        parameters=GraphParameters(
                            plant_id=state.context.active_plant.plant_id,
                            part_id=state.context.active_part,
                            compound_id=next(iter(state.context.active_compounds), None),
                            target_id=state.context.active_target,
                        ),
                    ),
                )
            )
        return self._failure(
            invocation, FailureType.UNSUPPORTED_OPERATION, "Capability unavailable"
        )

    @staticmethod
    def _failure(
        invocation: AgentInvocation, error: FailureType, reason: str, retryable: bool = False
    ) -> Failure:
        return Failure(invocation=invocation, error_type=error, reason=reason, retryable=retryable)
