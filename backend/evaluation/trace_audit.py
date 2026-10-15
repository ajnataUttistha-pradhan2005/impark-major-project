"""Offline invariants for a complete bounded run trace, independent of action order."""

from uuid import UUID

from pydantic import Field

from backend.contracts.base import Contract
from backend.trace.models import EventType, TraceEvent


class TraceAudit(Contract):
    run_id: UUID
    passed: bool
    event_count: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    invocation_count: int = Field(ge=0)
    issues: list[str] = Field(default_factory=list)


def audit_run(
    events: list[TraceEvent],
    run_id: UUID,
    *,
    expected_outcome: str,
    dropped: int = 0,
    write_failures: int = 0,
) -> TraceAudit:
    """Reject lost or internally inconsistent traces; never infer correctness from one path."""
    selected = [event for event in events if event.correlation.run_id == run_id]
    kinds = [event.event_type for event in selected]
    issues: list[str] = []
    if not selected:
        issues.append("No events for run")
    if dropped or write_failures:
        issues.append("Trace recorder lost domain events")
    if len({event.correlation.session_id for event in selected}) > 1:
        issues.append("Run events cross session boundaries")
    if selected and EventType.TURN_STARTED not in kinds:
        issues.append("Missing turn start")
    decisions = [event for event in selected if event.event_type == EventType.DECISION_MADE]
    for event in decisions:
        offered = (
            {candidate.name for candidate in event.snapshot.candidate_actions}
            if event.snapshot
            else set()
        )
        if event.action not in offered:
            issues.append("Decision selected an action absent from its candidate set")
    started = kinds.count(EventType.AGENT_INVOCATION_STARTED)
    finished = kinds.count(EventType.AGENT_INVOCATION_COMPLETED) + kinds.count(
        EventType.AGENT_INVOCATION_FAILED
    )
    if started != finished:
        issues.append("Agent invocation start/completion mismatch")
    for position, kind in enumerate(kinds):
        if (
            kind == EventType.FINAL_LLM_STARTED
            and EventType.RESPONSE_CONTEXT_BUILT not in kinds[:position]
        ):
            issues.append("Final LLM started before deterministic response context")
        if (
            kind == EventType.FINAL_LLM_COMPLETED
            and EventType.FINAL_LLM_STARTED not in kinds[:position]
        ):
            issues.append("Final LLM completed without start")
    if expected_outcome == "WAITING_USER":
        if EventType.CLARIFICATION_REQUESTED not in kinds or EventType.FINAL_LLM_STARTED in kinds:
            issues.append("Clarification trace has an invalid response lifecycle")
    else:
        if EventType.TURN_COMPLETED not in kinds or EventType.FINAL_LLM_COMPLETED not in kinds:
            issues.append("Terminal trace lacks response or completion")
        elif kinds.index(EventType.FINAL_LLM_COMPLETED) > kinds.index(EventType.TURN_COMPLETED):
            issues.append("Turn completed before final response")
    return TraceAudit(
        run_id=run_id,
        passed=not issues,
        event_count=len(selected),
        decision_count=len(decisions),
        invocation_count=started,
        issues=issues,
    )
