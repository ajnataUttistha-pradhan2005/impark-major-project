from opentelemetry import trace

from backend.state.models import ConversationState
from backend.trace.models import EventType, StateSnapshot, TraceEvent
from backend.trace.recorder import TraceRecorder

tracer = trace.get_tracer("impark")


def emit_state(recorder: TraceRecorder, state: ConversationState, event: EventType) -> None:
    context = state.correlation.model_copy(deep=True)
    context.iteration = state.iteration
    span = trace.get_current_span().get_span_context()
    if span.is_valid:
        context.trace_id = format(span.trace_id, "032x")
        context.span_id = format(span.span_id, "016x")
    snapshot = StateSnapshot(
        active_plant_id=(
            state.context.active_plant.plant_id if state.context.active_plant else None
        ),
        hypothesis_ids=[h.candidate.plant_id for h in state.belief.hypotheses],
        hypothesis_confidences=[h.candidate.confidence for h in state.belief.hypotheses],
        evidence_refs=[e.evidence_id for e in state.evidence.all_evidence()],
        observation_refs=[o.observation_id for o in state.execution.observations],
        failure_refs=[f.failure_id for f in state.execution.failures],
        pending_objective_ids=[o.objective_id for o in state.goal.pending],
        candidate_actions=state.available_actions,
        contradiction_count=len(state.evidence.contradictions),
        gap_count=len(state.evidence.gaps),
        status=state.termination.status,
        mode=state.session.mode,
        confidence=state.belief.confidence,
    )
    recorder.emit(
        TraceEvent(
            correlation=context,
            event_type=event,
            snapshot=snapshot,
            action=state.last_decision.selected.name if state.last_decision else None,
        )
    )
