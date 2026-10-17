from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from backend.contracts.agents import CandidatePlant
from backend.contracts.base import Contract, CorrelationMetadata
from backend.contracts.evidence import Evidence


class ClarificationRequest(Contract):
    clarification_id: UUID = Field(default_factory=uuid4)
    question: str = "Please provide a clearer plant name or select a supplied candidate."
    candidates: list[CandidatePlant] = Field(default_factory=list)


class ClarificationResponse(Contract):
    clarification_id: UUID
    text: str = Field(default="Selected candidate", min_length=1, max_length=8000)
    selected_plant_id: str | None = None
    image_id: UUID | None = None


class ResponseContext(Contract):
    intent: str
    user_question: str = Field(default="", max_length=8000)
    answer_style: Literal["overview", "explanation"] = "overview"
    resolved_plant: CandidatePlant | None = None
    text_evidence: list[Evidence] = Field(default_factory=list)
    image_evidence: list[Evidence] = Field(default_factory=list)
    graph_evidence: list[Evidence] = Field(default_factory=list)
    known_topics: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    safety_constraints: tuple[str, ...] = (
        "Educational use only; not medical advice.",
        "Do not invent dosage, treatment claims, sources, or stronger evidence classes.",
    )
    outcome: str


class FinalResponseRequest(Contract):
    response_context: ResponseContext


class FinalResponse(Contract):
    text: str
    citation_ids: list[UUID] = Field(default_factory=list)
    placeholder: bool = True
    provider: str = "deterministic"
    model: str | None = None
    fallback_used: bool = False


class ResponseChunk(Contract):
    text: str = Field(default="", max_length=16000)
    citation_ids: list[UUID] = Field(default_factory=list, max_length=100)
    provider: str = "deterministic"
    model: str | None = None
    fallback_used: bool = False


class ServerEventType(StrEnum):
    SESSION_ESTABLISHED = "session_established"
    TURN_STARTED = "turn_started"
    ACTION_SELECTED = "action_selected"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    OBSERVATION_RECEIVED = "observation_received"
    CLARIFICATION_REQUESTED = "clarification_requested"
    RESPONSE_STARTED = "response_started"
    RESPONSE_DELTA = "response_delta"
    RESPONSE_COMPLETED = "response_completed"
    ERROR = "error"
    TURN_COMPLETED = "turn_completed"


class ServerEvent(Contract):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: ServerEventType
    correlation: CorrelationMetadata
    text_delta: str | None = None
    clarification: ClarificationRequest | None = None


ResponseStreamEvent = ServerEvent
ResponseStream = AsyncIterator[ResponseStreamEvent]
