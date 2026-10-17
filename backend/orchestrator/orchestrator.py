"""Harness operations. LangGraph nodes delegate here; agents never own global state."""

import asyncio
from time import perf_counter

from backend.contracts.actions import ActionName, ActionRecord, Capability
from backend.contracts.agents import Failure, GraphAgentOutput, ImageAgentResult, TextResult
from backend.contracts.response import ClarificationRequest, FinalResponse, FinalResponseRequest
from backend.database.postgres.client import StoreError
from backend.evidence.context_builder import build_response_context
from backend.evidence.evaluator import evaluate_observation
from backend.evidence.reference import ReferenceNotes
from backend.llm.provider import LLMProvider
from backend.orchestrator.actions import REGISTRY
from backend.orchestrator.decision import DecisionEngine
from backend.orchestrator.execution import ExecutionManager
from backend.orchestrator.recovery import fingerprint
from backend.orchestrator.termination import check_termination
from backend.services.live import publish
from backend.state.goals import ObjectiveStatus
from backend.state.models import ConversationState, SessionMode, TaskStatus
from backend.trace.instrumentation import emit_state, tracer
from backend.trace.models import EventType, TraceEvent
from backend.trace.recorder import TraceRecorder


class Harness:
    def __init__(
        self,
        decision: DecisionEngine,
        execution: ExecutionManager,
        llm: LLMProvider,
        trace: TraceRecorder,
        reference_notes: ReferenceNotes | None = None,
    ) -> None:
        self.decision, self.execution, self.llm, self.trace = decision, execution, llm, trace
        self.reference_notes = reference_notes

    def emit(self, state: ConversationState, event: EventType) -> None:
        emit_state(self.trace, state, event)
        if event in {
            EventType.TURN_STARTED,
            EventType.AGENT_INVOCATION_STARTED,
            EventType.CLARIFICATION_REQUESTED,
            EventType.RESPONSE_CONTEXT_BUILT,
        }:
            publish(
                "progress",
                {
                    "stage": event.value,
                    "mode": state.session.mode.value,
                    "run_id": str(state.correlation.run_id),
                },
            )

    def observe(self, state: ConversationState) -> None:
        state.termination.status = TaskStatus.RUNNING
        self.emit(state, EventType.TURN_STARTED)

    def assess(self, state: ConversationState) -> None:
        if self.decision.policy.identity_resolved(state):
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
            if invocation.capability == Capability.GRAPH:
                objective = next(o for o in state.goal.pending if o.query_type is not None)
                assert objective.query_type is not None
                emit_state(
                    self.trace,
                    state,
                    EventType.TOOL_CALL_STARTED,
                    {"query_type": objective.query_type.value, "read_only": True},
                )
            started = perf_counter()
            with tracer.start_as_current_span(f"agent.{invocation.capability.value}"):
                state.execution.pending_result = await self.execution.execute(state, invocation)
            emit_state(
                self.trace,
                state,
                EventType.AGENT_INVOCATION_FAILED
                if isinstance(state.execution.pending_result, Failure)
                else EventType.AGENT_INVOCATION_COMPLETED,
                {
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "capability": invocation.capability.value,
                    "attempt": invocation.retry.attempt,
                },
            )
            if invocation.capability == Capability.GRAPH:
                result = state.execution.pending_result
                details: dict[str, str | int | float | bool] = {
                    "duration_ms": round((perf_counter() - started) * 1000, 3)
                }
                if not isinstance(result, Failure) and isinstance(result.payload, GraphAgentOutput):
                    details.update(
                        evidence_count=len(result.payload.evidence),
                        gap_count=len(result.payload.gaps),
                        contradiction_count=len(result.payload.contradictions),
                        truncated=result.payload.truncated,
                    )
                emit_state(
                    self.trace,
                    state,
                    EventType.TOOL_CALL_FAILED
                    if isinstance(result, Failure)
                    else EventType.TOOL_CALL_COMPLETED,
                    details,
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
            locked = state.session.locked_plant_id or (
                state.context.active_plant.plant_id if state.context.active_plant else None
            )
            if locked and candidate.plant_id != locked:
                state.termination.ready_for_response = True
                state.termination.reason = TaskStatus.SCOPE_REJECTED
                return
            state.session.locked_plant_id = candidate.plant_id
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
            question = next(
                (
                    o.payload.clarification_question
                    for o in reversed(state.execution.observations)
                    if isinstance(o.payload, (TextResult, ImageAgentResult))
                    and o.payload.clarification_question
                ),
                None,
            )
            state.clarification = ClarificationRequest(
                candidates=(
                    []
                    if state.session.locked_plant_id or state.context.active_plant
                    else [h.candidate for h in state.belief.hypotheses]
                ),
                question=question
                or (
                    "Which aspect of this plant would you like to explore?"
                    if state.session.locked_plant_id or state.context.active_plant
                    else "Which plant do you mean? Please select a candidate or clarify."
                ),
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
                    TaskStatus.SCOPE_REJECTED,
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
            if isinstance(result.payload, TextResult):
                for stage in result.payload.stages:
                    self.trace.emit(
                        TraceEvent(
                            correlation=state.correlation.model_copy(deep=True),
                            event_type=EventType.TOOL_CALL_COMPLETED,
                            component="text",
                            details={
                                "stage": stage,
                                "candidate_count": len(result.payload.candidates),
                            },
                        )
                    )
                if result.invocation.action.name == ActionName.REASSESS_ENTITY:
                    self.emit(state, EventType.ENTITY_REASSESSED)
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
        if self.reference_notes is not None and state.response_context.graph_evidence:
            try:
                async with asyncio.timeout(2):
                    notes = await self.reference_notes.for_context(state.response_context)
                existing = {item.evidence_id for item in state.evidence.all_evidence()}
                for note in notes:
                    if note.evidence_id not in existing:
                        state.evidence.text.append(note)
                        state.response_context.text_evidence.append(note.model_copy(deep=True))
                        existing.add(note.evidence_id)
                if notes:
                    self.emit(state, EventType.EVIDENCE_ADDED)
                    self.emit(state, EventType.RESPONSE_CONTEXT_BUILT)
            except (StoreError, TimeoutError):
                pass  # Optional explanation cache cannot fail the user's answer.
        self.emit(state, EventType.FINAL_LLM_STARTED)
        self.emit(state, EventType.RESPONSE_STREAM_STARTED)
        try:
            async with asyncio.timeout(state.budgets.action_timeout_seconds):
                request = FinalResponseRequest(
                    response_context=state.response_context.model_copy(deep=True)
                )
                publish("response_started", {"run_id": str(state.correlation.run_id)})
                streaming = getattr(self.llm, "stream", None)
                if streaming is not None:
                    from backend.contracts.response import ResponseChunk

                    chunks: list[ResponseChunk] = []
                    text_size = 0
                    allowed = {e.evidence_id for e in state.evidence.all_evidence()}
                    async for chunk in streaming(request):
                        chunk = ResponseChunk.model_validate(chunk.model_dump())
                        if not set(chunk.citation_ids) <= allowed:
                            raise ValueError("Invalid streamed citation")
                        text_size += len(chunk.text)
                        if text_size > 128000 or len(chunks) >= 1200:
                            raise ValueError("Response stream exceeded its output budget")
                        chunks.append(chunk)
                        publish("response_delta", chunk.model_dump(mode="json"))
                    state.response = FinalResponse(
                        text="".join(c.text for c in chunks),
                        placeholder=False,
                        citation_ids=list(dict.fromkeys(i for c in chunks for i in c.citation_ids)),
                        provider=chunks[-1].provider if chunks else "grounded",
                        model=chunks[-1].model if chunks else None,
                        fallback_used=any(c.fallback_used for c in chunks),
                    )
                else:
                    state.response = await self.llm.generate(request)
            allowed = {e.evidence_id for e in state.evidence.all_evidence()}
            if not set(state.response.citation_ids) <= allowed:
                raise ValueError("Response provider invented a citation")
            if streaming is None:
                publish("response_delta", {"text": state.response.text})
        except Exception:
            # Provider boundary: no exception details or invalid output reach the client.
            state.termination.reason = TaskStatus.FAILED
            state.response = FinalResponse(
                text="Response generation unavailable. Educational use only; not medical advice."
            )
            publish("response_reset", {"reason": "generation_failed"})
            publish("response_delta", {"text": state.response.text})
        publish("response_completed", state.response.model_dump(mode="json"))
        self.emit(state, EventType.RESPONSE_STREAM_COMPLETED)
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
