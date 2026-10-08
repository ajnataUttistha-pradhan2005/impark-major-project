from typing import cast

from fastapi import Request

from backend.services.conversations import ConversationService
from backend.services.errors import ServiceError


def get_service(request: Request) -> ConversationService:
    return cast(ConversationService, request.app.state.conversations)


async def authorize_development(request: Request) -> None:
    """Central auth hook. Fail closed unless explicitly using local development API."""
    settings = request.app.state.settings
    if settings.application_env != "development" or not settings.enable_development_api:
        raise ServiceError(
            "FORBIDDEN", "Development API is disabled; authentication is pending", 403
        )
