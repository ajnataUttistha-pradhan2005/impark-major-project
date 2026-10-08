"""Harness operations. LangGraph nodes delegate here; agents never own global state."""

import asyncio

from backend.contracts.actions import ActionName, ActionRecord, Capability
from backend.contracts.agents import Failure, GraphAgentOutput
from backend.contracts.response import ClarificationRequest, FinalResponse, FinalResponseRequest
from backend.evidence.context_builder import build_response_context
from backend.evidence.evaluator import evaluate_observation
from backend.llm.provider import LLMProvider
from backend.orchestrator.actions import REGISTRY
from backend.orchestrator.decision import DecisionEngine
from backend.orchestrator.execution import ExecutionManager
from backend.orchestrator.recovery import fingerprint
from backend.orchestrator.termination import check_termination
from backend.state.goals import ObjectiveStatus
from backend.state.models import ConversationState, SessionMode, TaskStatus
from backend.trace.instrumentation import emit_state
from backend.trace.models import EventType
from backend.trace.recorder import TraceRecorder


class Harness:
    def __init__(
        self,
        decision: DecisionEngine,
        execution: ExecutionManager,
        llm: LLMProvider,
        trace: TraceRecorder,
    ) -> None:
        self.decision, self.execution, self.llm, self.trace = decision, execution, llm, trace

    def emit(self, state: ConversationState, event: EventType) -> None:
        emit_state(self.trace, state, event)

    def observe(self, state: ConversationState) -> None:
        state.termination.status = TaskStatus.RUNNING
        self.emit(state, EventType.TURN_STARTED)

    def assess(self, state: ConversationState) -> None:
        if self.decision.policy.resolved(state):
            for objective in state.goal.pending:
                if objective.query_type is None:
                    objective.status = ObjectiveStatus.COMPLETE
        self.emit(state, EventType.GOAL_ASSESSED)

    def enumerate_actions(self, state: ConversationState) -> None:
        state.available_actions = self.decision.candidates(state)
        self.emit(state, EventType.ACTION_CANDIDATE_GENERATED)

    def decide(self, state: ConversationState) -> None:
        state.last_decision = self.decision.decide_next_action(state)
        state.correlation.decision_id = state.last_decision.decision_id
        state.correlation.action_id = state.last_decision.selected.action_id
        state.correlation.agent_invocation_id = None
        self.emit(state, EventType.DECISION_MADE)

    async def dispatch(self, state: ConversationState) -> None:
        assert state.last_decision is not None
        action = state.last_decision.selected
        if action.name not in self.decision.policy.enumerate(state):
            raise ValueError("Action is no longer eligible")
        key = fingerprint(state, action.name)
        if action.name not in {
            ActionName.GENERATE_RESPONSE,
            ActionName.COMPLETE,
            ActionName.ABSTAIN,
        }:
            state.iteration += 1
        capability = REGISTRY[action.name].capability
        if capability in {Capability.TEXT, Capability.IMAGE, Capability.GRAPH} or (
            action.name == ActionName.RETRY_ACTION
        ):
            invocation = self.execution.invocation(state, action)
            if action.name == ActionName.RETRY_ACTION:
                self.emit(state, EventType.RETRY_STARTED)
            self.emit(state, EventType.AGENT_INVOCATION_STARTED)
            state.execution.pending_result = await self.execution.execute(state, invocation)
            self.emit(
                state,
                EventType.AGENT_INVOCATION_FAILED
                if isinstance(state.execution.pending_result, Failure)
                else EventType.AGENT_INVOCATION_COMPLETED,
            )
            if action.name == ActionName.RETRY_ACTION:
                state.execution.actions.append(
                    ActionRecord(
                        action=invocation.action,
                        fingerprint=fingerprint(state, invocation.action.name),
                        status="retried",
                        iteration=state.iteration,
                    )
                )
                self.emit(state, EventType.RETRY_COMPLETED)
        else:
            self._control(state, action.name)
        state.execution.actions.append(
            ActionRecord(
                action=action,
                fingerprint=key,
                status="executed",
                iteration=state.iteration,
            )
        )

    def _control(self, state: ConversationState, name: ActionName) -> None:
        if name == ActionName.UPDATE_CONTEXT:
            candidate = max(
                (h.candidate for h in state.belief.hypotheses if not h.weakened),
                key=lambda c: c.confidence,
            )
            state.context.active_plant = candidate.model_copy(deep=True)
            state.belief.confidence = candidate.confidence
            state.session.mode = SessionMode.CONVERSATION
            for objective in state.goal.pending:
                if objective.query_type is None:
                    objective.status = ObjectiveStatus.COMPLETE
        elif name == ActionName.RECONCILE_MODALITIES:
            for contradiction in state.evidence.contradictions:
                contradiction.reconciled = True
            state.belief.requires_reassessment = bool(state.user_message)
            state.belief.confidence = min(state.belief.confidence, 0.79)
        elif name == ActionName.ASK_CLARIFICATION:
            state.clarification = ClarificationRequest(
                candidates=[h.candidate for h in state.belief.hypotheses]
            )
            state.clarification_count += 1
            state.termination.status = TaskStatus.WAITING_USER
            self.emit(state, EventType.CLARIFICATION_REQUESTED)
        elif name == ActionName.ABSTAIN:
            state.termination.ready_for_response = True
            state.termination.reason = (
                TaskStatus.MAX_ITERATIONS_REACHED
                if state.iteration >= state.budgets.max_iterations
                else TaskStatus.EVIDENCE_UNAVAILABLE
            )
        elif name == ActionName.COMPLETE:
            reason = state.termination.reason
            state.termination.status = (
                TaskStatus(reason)
                if reason
                in {
                    TaskStatus.MAX_ITERATIONS_REACHED,
                    TaskStatus.EVIDENCE_UNAVAILABLE,
                    TaskStatus.SAFETY_ABSTENTION,
                    TaskStatus.FAILED,
                }
                else TaskStatus.COMPLETE
            )
            self.emit(state, EventType.TERMINATION_REACHED)
            self.emit(state, EventType.TURN_COMPLETED)

    def collect(self, state: ConversationState) -> None:
        result = state.execution.pending_result
        if isinstance(result, Failure):
            state.execution.failures.append(result)
            capability = result.invocation.capability
            if capability == Capability.TEXT:
                state.belief.text_pending = False
                state.belief.requires_reassessment = False
            elif capability == Capability.IMAGE:
                state.belief.image_pending = False
        elif result is not None:
            state.execution.observations.append(result)
            self.emit(state, EventType.OBSERVATION_CREATED)

    def evaluate(self, state: ConversationState) -> None:
        result = state.execution.pending_result
        if result is not None and not isinstance(result, Failure):
            evaluate_observation(state, result)
            if isinstance(result.payload, GraphAgentOutput) and result.payload.placeholder:
                state.termination.ready_for_response = True
                state.termination.reason = TaskStatus.EVIDENCE_UNAVAILABLE
            self.emit(state, EventType.EVIDENCE_EVALUATED)
            if state.evidence.all_evidence():
                self.emit(state, EventType.EVIDENCE_ADDED)
            if state.evidence.gaps:
                self.emit(state, EventType.EVIDENCE_GAP_DETECTED)
            if state.evidence.contradictions:
                self.emit(state, EventType.CONTRADICTION_DETECTED)
        state.execution.pending_result = None

    def update(self, state: ConversationState) -> None:
        self.emit(state, EventType.BELIEF_UPDATED)
        self.emit(state, EventType.STATE_SNAPSHOT)

    def terminate(self, state: ConversationState) -> None:
        check_termination(state, self.decision.policy)
        self.emit(state, EventType.TERMINATION_CHECKED)

    def context(self, state: ConversationState) -> None:
        # Policy permits generation only for fulfilled objectives or a transparent limitation.
        if ActionName.GENERATE_RESPONSE not in self.decision.policy.enumerate(state):
            raise ValueError("Response generation is not eligible")
        state.termination.ready_for_response = True
        state.response_context = build_response_context(state)
        self.emit(state, EventType.RESPONSE_CONTEXT_BUILT)

    async def generate(self, state: ConversationState) -> None:
        assert state.response_context is not None
        self.emit(state, EventType.FINAL_LLM_STARTED)
        try:
            async with asyncio.timeout(state.budgets.action_timeout_seconds):
                state.response = await self.llm.generate(
                    FinalResponseRequest(
                        response_context=state.response_context.model_copy(deep=True)
                    )
                )
            allowed = {e.evidence_id for e in state.evidence.all_evidence()}
            if not set(state.response.citation_ids) <= allowed:
                raise ValueError("Response provider invented a citation")
        except Exception:
            # Provider boundary: no exception details or invalid output reach the client.
            state.termination.reason = TaskStatus.FAILED
            state.response = FinalResponse(
                text="Response generation unavailable. Educational use only; not medical advice."
            )
        assert state.last_decision is not None
        state.execution.actions.append(
            ActionRecord(
                action=state.last_decision.selected,
                fingerprint=fingerprint(state, ActionName.GENERATE_RESPONSE),
                status="failed" if state.termination.reason == TaskStatus.FAILED else "executed",
                iteration=state.iteration,
            )
        )
        self.emit(state, EventType.FINAL_LLM_COMPLETED)
