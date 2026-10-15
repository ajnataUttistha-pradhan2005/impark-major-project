from uuid import UUID, uuid4

from backend.agents.image.preprocessing import validate_image
from backend.contracts.agents import ImageReference
from backend.services.conversations import ConversationService
from backend.services.errors import ServiceError


async def register_image(
    service: ConversationService,
    session_id: UUID,
    content: bytes,
    mime: str,
) -> ImageReference:
    await service.load(session_id)
    from backend.database.postgres.persistence import PostgresSessionRepository

    if isinstance(service.repository, PostgresSessionRepository):
        from backend.database.postgres.chat import ChatStore
        from backend.services.chat_images import ChatImages

        reference = await ChatImages(ChatStore(service.repository.client), service.settings).upload(
            session_id, content, mime
        )
        service.images.setdefault(session_id, {})[reference.image_id] = reference
        return reference
    try:
        metadata = await validate_image(
            content,
            mime,
            service.settings.max_image_bytes,
            service.settings.max_image_pixels,
        )
    except ValueError as exc:
        raise ServiceError("INVALID_INPUT", "Invalid or unsupported image", 422) from exc
    reference = ImageReference(image_id=uuid4(), metadata=metadata)
    # Placeholder model does not consume pixels. No filesystem paths/remote URL fetches.
    # TODO R-005: durable upload lifecycle and model-accessible blob repository.
    service.images.setdefault(session_id, {})[reference.image_id] = reference
    return reference
