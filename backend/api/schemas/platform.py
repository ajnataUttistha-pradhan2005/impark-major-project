"""Versioned frontend contract; all messages and events have durable identifiers."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from backend.api.schemas.chat import ChatRequest, ChatResponse
from backend.contracts.base import Contract
from backend.contracts.evidence import Evidence
from backend.contracts.response import ClarificationResponse


class SessionCreate(Contract):
    title: str = Field(default="New chat", min_length=1, max_length=120)


class SessionPatch(Contract):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None


class SessionSummary(Contract):
    session_id: UUID
    title: str
    archived: bool
    created_at: datetime
    updated_at: datetime
    state: ChatResponse


class SessionPage(Contract):
    items: list[SessionSummary]
    next_offset: int | None = None


class TurnCreate(ChatRequest):
    request_id: UUID


class ClarificationCreate(ClarificationResponse):
    request_id: UUID


class RunView(Contract):
    operation_id: UUID
    session_id: UUID
    status: Literal["accepted", "running", "interrupted", "complete", "cancelled", "failed"]
    result: ChatResponse | None = None
    error_code: str | None = None
    events_url: str


class MessageView(Contract):
    message_id: UUID
    operation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    status: str
    data: dict[str, Any]
    created_at: datetime


class MessagePage(Contract):
    items: list[MessageView]
    next_offset: int | None = None


class StreamEvent(Contract):
    version: Literal[1] = 1
    operation_id: UUID
    sequence: int = Field(ge=1)
    type: Literal[
        "run_started",
        "progress",
        "response_started",
        "response_delta",
        "response_reset",
        "response_completed",
        "clarification_requested",
        "run_completed",
        "run_failed",
        "run_cancelled",
        "run_interrupted",
    ]
    payload: dict[str, Any]


class EvidencePage(Contract):
    items: list[Evidence]
