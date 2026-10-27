"""Shared primitives. No infrastructure or agent implementation dependencies."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

Confidence = Annotated[float, Field(ge=0, le=1)]
EntityId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\w:.-]+$")]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CorrelationMetadata(Contract):
    session_id: UUID
    turn_id: UUID | None = None
    run_id: UUID | None = None
    iteration: int = Field(default=0, ge=0)
    decision_id: UUID | None = None
    action_id: UUID | None = None
    agent_invocation_id: UUID | None = None
    correlation_id: UUID = Field(default_factory=uuid4)
    trace_id: str | None = None
    span_id: str | None = None

    @field_validator(
        "session_id",
        "turn_id",
        "run_id",
        "decision_id",
        "action_id",
        "agent_invocation_id",
        "correlation_id",
        mode="before",
    )
    @classmethod
    def _normalize_uuid(cls, value: Any) -> Any:
        if isinstance(value, UUID) and type(value) is not UUID:
            return UUID(str(value))
        return value
