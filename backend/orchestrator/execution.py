import asyncio
from uuid import uuid4

from backend.agents.common.contracts import Agent
from backend.contracts.actions import Action, ActionName, AgentInvocation, Capability, RetryMetadata
from backend.contracts.agents import (
    Failure,
    FailureType,
    GraphAgentInput,
    GraphAgentOutput,
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
                result = await self._invoke(state, invocation.model_copy(deep=True))
            # Revalidate mutable provider models, including nested payload constraints.
            result = type(result).model_validate(result.model_dump(mode="python"))
            # Reject forged lineage/provider contract mismatch at the capability boundary.
            if result.invocation != invocation:
                return self._failure(invocation, FailureType.PERMANENT, "Invalid result lineage")
            if isinstance(result, Observation) and result.component != invocation.capability:
                return self._failure(invocation, FailureType.PERMANENT, "Invalid result capability")
            if isinstance(result, Observation) and isinstance(result.payload, GraphAgentOutput):
                objective = next(o for o in state.goal.pending if o.query_type is not None)
                claimed = set(result.payload.completed_objectives)
                claimed.update(g.objective_id for g in result.payload.gaps)
                if claimed - {objective.objective_id}:
                    return self._failure(
                        invocation, FailureType.PERMANENT, "Invalid objective scope"
                    )
                if any(e.modality.value != "graph" for e in result.payload.evidence):
                    return self._failure(
                        invocation, FailureType.PERMANENT, "Invalid evidence modality"
                    )
                if any(
                    e.graph_scope
                    and e.graph_scope.get("plant_id")
                    != (state.context.active_plant.plant_id if state.context.active_plant else None)
                    for e in result.payload.evidence
                ):
                    return self._failure(
                        invocation,
                        FailureType.POLICY_REJECTION,
                        "Graph evidence is outside the active plant scope",
                    )
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
                    active_plant=state.context.active_plant.model_copy(deep=True)
                    if state.context.active_plant
                    else None,
                    active_compound_id=(
                        state.context.active_compounds[-1]
                        if state.context.active_topic == "compound"
                        and state.context.active_compounds
                        else None
                    ),
                    recent_query_types=state.context.recent_query_types,
                    excluded_plant_ids=[
                        h.candidate.plant_id for h in state.belief.hypotheses if h.weakened
                    ],
                )
            )
        if invocation.capability == Capability.IMAGE and state.image is not None:
            return await self.image.execute(
                ImageAgentInput(invocation=invocation, image=state.image.model_copy(deep=True))
            )
        if invocation.capability == Capability.GRAPH:
            objective = next(o for o in state.goal.pending if o.query_type is not None)
            assert objective.query_type is not None
            active = state.context.active_plant
            if active is None:
                return self._failure(
                    invocation,
                    FailureType.POLICY_REJECTION,
                    "Establish one plant before graph retrieval",
                )
            parameters = (
                objective.parameters.model_copy(deep=True)
                if objective.parameters
                else (GraphParameters(part_id=state.context.active_part))
            )
            if (
                (parameters.plant_id and parameters.plant_id != active.plant_id)
                or (parameters.comparison_plant_id is not None)
                or (
                    state.session.locked_plant_id
                    and state.session.locked_plant_id != active.plant_id
                )
            ):
                return self._failure(
                    invocation,
                    FailureType.POLICY_REJECTION,
                    "Graph request is outside this session's plant scope",
                )
            parameters.plant_id = active.plant_id
            return await self.graph.execute(
                GraphAgentInput(
                    invocation=invocation,
                    objective_ids=[objective.objective_id],
                    evidence_gaps=[gap.model_copy(deep=True) for gap in state.evidence.gaps],
                    prior_evidence=[
                        e.model_copy(deep=True) for e in state.context.citation_history
                    ],
                    query=GraphQuery(
                        query_type=objective.query_type,
                        parameters=parameters,
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
