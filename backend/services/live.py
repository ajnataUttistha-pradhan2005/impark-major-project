"""Request-local public progress sink; separate from non-interfering domain tracing."""

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

publisher: ContextVar[Callable[[str, dict[str, Any]], None] | None] = ContextVar(
    "public_event_publisher", default=None
)


def publish(kind: str, payload: dict[str, Any]) -> None:
    callback = publisher.get()
    if callback is not None:
        callback(kind, payload)
