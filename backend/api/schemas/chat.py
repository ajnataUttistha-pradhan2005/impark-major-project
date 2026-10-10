from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.contracts.agents import CandidatePlant, TextResult
from backend.contracts.base import Contract, CorrelationMetadata
from backend.contracts.response import ClarificationRequest, FinalResponse
from backend.state.models import SessionMode, TaskStatus


class ChatRequest(Contract):
    text: str | None = Field(default=None, max_length=8000)
    image_id: UUID | None = None
    selected_plant_id: UUID | None = None

    @model_validator(mode="after")
    def meaningful_input(self) -> Self:
        if self.text is not None:
            object.__setattr__(self, "text", self.text.strip())
        if not self.text and self.image_id is None and self.selected_plant_id is None:
            raise ValueError("Provide non-empty text or an uploaded image")
        return self


class ChatResponse(Contract):
    correlation: CorrelationMetadata
    mode: SessionMode
    status: TaskStatus
    active_plant: CandidatePlant | None = None
    clarification: ClarificationRequest | None = None
    response: FinalResponse | None = None
    understanding: TextResult | None = None
    session_notice: str = (
        "Each chat supports one plant. Once a plant is established, start a new chat "
        "to discuss another plant."
    )


class AutocompleteResponse(Contract):
    candidates: list[CandidatePlant] = Field(default_factory=list)
    implemented: bool = False
    detail: str = "Entity search provider is not configured"


class ErrorResponse(Contract):
    code: str
    message: str
    correlation_id: UUID
