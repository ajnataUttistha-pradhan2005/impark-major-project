from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from backend.contracts.actions import ActionCandidate, ActionName, ActionRecord, Decision
from backend.contracts.agents import CandidatePlant, Failure, ImageReference, Observation
from backend.contracts.base import Confidence, Contract, CorrelationMetadata, EntityId
from backend.contracts.evidence import EvidenceState, Modality
from backend.contracts.response import ClarificationRequest, FinalResponse, ResponseContext
from backend.state.goals import Goal


class SessionMode(StrEnum):
    DISCOVERY = "discovery"
    CONVERSATION = "conversation"


class TaskStatus(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    ABSTAINED = "ABSTAINED"
    WAITING_USER = "WAITING_USER"
    FAILED = "FAILED"
    MAX_ITERATIONS_REACHED = "MAX_ITERATIONS_REACHED"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    SAFETY_ABSTENTION = "SAFETY_ABSTENTION"


class Session(Contract):
    session_id: UUID = Field(default_factory=uuid4)
    mode: SessionMode = SessionMode.DISCOVERY


class Hypothesis(Contract):
    candidate: CandidatePlant
    modality: Modality
    weakened: bool = False


class BeliefState(Contract):
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    confidence: Confidence = 0
    requires_reassessment: bool = False
    text_pending: bool = False
    image_pending: bool = False


class ConversationContext(Contract):
    active_plant: CandidatePlant | None = None
    active_part: str | None = None
    active_compounds: list[EntityId] = Field(default_factory=list)
    active_target: EntityId | None = None
    active_topic: str | None = None


class Budgets(Contract):
    max_iterations: int = Field(default=8, ge=1, le=8)
    max_agent_retries: int = Field(default=2, ge=0, le=2)
    repeated_action_threshold: int = Field(default=2, ge=1, le=2)
    max_action_calls: int = Field(default=3, ge=1, le=8)
    max_clarifications: int = Field(default=2, ge=0, le=2)
    action_timeout_seconds: float = Field(default=10, gt=0, le=60)


class TerminationState(Contract):
    status: TaskStatus = TaskStatus.READY
    reason: str | None = None
    ready_for_response: bool = False

    @property
    def terminal(self) -> bool:
        return self.status not in {TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.WAITING_USER}


class ExecutionState(Contract):
    actions: list[ActionRecord] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)
    retry_counts: dict[ActionName, int] = Field(default_factory=dict)
    handled_failures: list[UUID] = Field(default_factory=list)
    pending_result: Observation | Failure | None = None


class ConversationState(Contract):
    session: Session = Field(default_factory=Session)
    correlation: CorrelationMetadata
    user_message: str = ""
    image: ImageReference | None = None
    goal: Goal = Field(default_factory=Goal)
    belief: BeliefState = Field(default_factory=BeliefState)
    context: ConversationContext = Field(default_factory=ConversationContext)
    evidence: EvidenceState = Field(default_factory=EvidenceState)
    execution: ExecutionState = Field(default_factory=ExecutionState)
    available_actions: list[ActionCandidate] = Field(default_factory=list)
    last_decision: Decision | None = None
    iteration: int = 0
    budgets: Budgets = Field(default_factory=Budgets)
    clarification: ClarificationRequest | None = None
    clarification_count: int = 0
    termination: TerminationState = Field(default_factory=TerminationState)
    response_context: ResponseContext | None = None
    response: FinalResponse | None = None

    @classmethod
    def new(cls, budgets: Budgets | None = None) -> "ConversationState":
        session = Session()
        return cls(
            session=session,
            correlation=CorrelationMetadata(session_id=session.session_id),
            budgets=budgets or Budgets(),
        )
