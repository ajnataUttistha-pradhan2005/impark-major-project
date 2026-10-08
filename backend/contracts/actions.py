from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from backend.contracts.base import Confidence, Contract, CorrelationMetadata


class ActionName(StrEnum):
    RESOLVE_TEXT_ENTITY = "RESOLVE_TEXT_ENTITY"
    ANALYZE_IMAGE = "ANALYZE_IMAGE"
    RETRIEVE_GRAPH = "RETRIEVE_GRAPH"
    RETRIEVE_ADDITIONAL_GRAPH_EVIDENCE = "RETRIEVE_ADDITIONAL_GRAPH_EVIDENCE"
    REASSESS_ENTITY = "REASSESS_ENTITY"
    RECONCILE_MODALITIES = "RECONCILE_MODALITIES"
    UPDATE_CONTEXT = "UPDATE_CONTEXT"
    RETRY_ACTION = "RETRY_ACTION"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    ABSTAIN = "ABSTAIN"
    GENERATE_RESPONSE = "GENERATE_RESPONSE"
    COMPLETE = "COMPLETE"


class Capability(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    GRAPH = "graph"
    CONTROL = "control"
    RESPONSE = "response"


class RetryMetadata(Contract):
    attempt: int = Field(default=0, ge=0)
    max_retries: int = Field(default=2, ge=0, le=2)
    original_action_id: UUID | None = None


class ActionDefinition(Contract):
    name: ActionName
    capability: Capability
    prerequisites: tuple[str, ...]
    safety_requirements: tuple[str, ...]
    goal_progress: Confidence = 0.8
    information_gain: Confidence = 0.8
    priority: Confidence = 0.5
    latency_cost: float = Field(default=0.02, ge=0)
    token_cost: float = Field(default=0, ge=0)
    retry_policy: RetryMetadata = Field(default_factory=RetryMetadata)


class Action(Contract):
    action_id: UUID = Field(default_factory=uuid4)
    name: ActionName
    retry_of: UUID | None = None


class ActionCandidate(Contract):
    name: ActionName
    score: float
    eligibility_reason: str


class Decision(Contract):
    decision_id: UUID = Field(default_factory=uuid4)
    selected: Action
    candidates: list[ActionCandidate]
    reason: str = "Highest deterministic score among policy-eligible actions"


class AgentInvocation(Contract):
    correlation: CorrelationMetadata
    action: Action
    capability: Capability
    retry: RetryMetadata = Field(default_factory=RetryMetadata)


class ActionRecord(Contract):
    action: Action
    fingerprint: str
    status: str
    iteration: int
