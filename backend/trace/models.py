from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from backend.contracts.actions import ActionCandidate, ActionName
from backend.contracts.base import Contract, CorrelationMetadata, utc_now


class EventType(StrEnum):
    SESSION_CREATED = "session_created"
    TURN_STARTED = "turn_started"
    GOAL_ASSESSED = "goal_assessed"
    HYPOTHESIS_CREATED = "hypothesis_created"
    HYPOTHESIS_UPDATED = "hypothesis_updated"
    HYPOTHESIS_REJECTED = "hypothesis_rejected"
    ACTION_CANDIDATE_GENERATED = "action_candidate_generated"
    DECISION_MADE = "decision_made"
    AGENT_INVOCATION_STARTED = "agent_invocation_started"
    AGENT_INVOCATION_COMPLETED = "agent_invocation_completed"
    AGENT_INVOCATION_FAILED = "agent_invocation_failed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"
    PARALLEL_EXECUTION_STARTED = "parallel_execution_started"
    PARALLEL_BRANCH_COMPLETED = "parallel_branch_completed"
    PARALLEL_BRANCH_CANCELLED = "parallel_branch_cancelled"
    OBSERVATION_CREATED = "observation_created"
    EVIDENCE_ADDED = "evidence_added"
    EVIDENCE_EVALUATED = "evidence_evaluated"
    EVIDENCE_GAP_DETECTED = "evidence_gap_detected"
    CONTRADICTION_DETECTED = "contradiction_detected"
    BELIEF_UPDATED = "belief_updated"
    ENTITY_REASSESSED = "entity_reassessed"
    RETRY_STARTED = "retry_started"
    RETRY_COMPLETED = "retry_completed"
    CLARIFICATION_REQUESTED = "clarification_requested"
    USER_INTERRUPTED = "user_interrupted"
    EXECUTION_RESUMED = "execution_resumed"
    TERMINATION_CHECKED = "termination_checked"
    TERMINATION_REACHED = "termination_reached"
    RESPONSE_CONTEXT_BUILT = "response_context_built"
    FINAL_LLM_STARTED = "final_llm_started"
    FINAL_LLM_COMPLETED = "final_llm_completed"
    RESPONSE_STREAM_STARTED = "response_stream_started"
    RESPONSE_STREAM_COMPLETED = "response_stream_completed"
    TURN_COMPLETED = "turn_completed"
    STATE_SNAPSHOT = "state_snapshot"


class StateSnapshot(Contract):
    """IDs, scores and control flags only; no prompts, documents or image bytes."""

    active_plant_id: str | None
    hypothesis_ids: list[str]
    hypothesis_confidences: list[float]
    evidence_refs: list[UUID]
    observation_refs: list[UUID]
    failure_refs: list[UUID]
    pending_objective_ids: list[UUID]
    candidate_actions: list[ActionCandidate]
    contradiction_count: int
    gap_count: int
    status: str
    mode: str
    confidence: float


class TraceEvent(Contract):
    event_id: UUID = Field(default_factory=uuid4)
    correlation: CorrelationMetadata
    parent_event_id: UUID | None = None
    event_type: EventType
    component: str = "orchestrator"
    action: ActionName | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    status: str = "ok"
    latency_ms: float | None = Field(default=None, ge=0)
    error_type: str | None = None
    evidence_refs: list[UUID] = Field(default_factory=list)
    snapshot: StateSnapshot | None = None
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)
