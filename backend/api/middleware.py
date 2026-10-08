import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CorrelationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            correlation_id = UUID(headers.get(b"x-correlation-id", b"").decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            correlation_id = uuid4()
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def correlated_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-correlation-id", str(correlation_id).encode())
                )
            await send(message)

        await self.app(scope, receive, correlated_send)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "service": "impark",
                "component": record.name,
                "event": record.getMessage(),
            }
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("backend")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
