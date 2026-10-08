from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from backend.contracts.response import ServerEvent


class ProgressStream(Protocol):
    """Transport-neutral protocol; SSE/WebSocket selection remains R-003."""

    def subscribe(self, session_id: UUID, run_id: UUID) -> AsyncIterator[ServerEvent]: ...
