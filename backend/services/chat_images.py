"""Image persistence and validation shared by transports; no classification here."""

from uuid import UUID, uuid4

from backend.agents.image.preprocessing import validate_image
from backend.config.settings import Settings
from backend.contracts.agents import ImageReference
from backend.database.postgres.chat import ChatStore
from backend.services.errors import ServiceError


class ChatImages:
    def __init__(self, store: ChatStore, settings: Settings) -> None:
        self.store, self.settings = store, settings

    async def upload(self, sid: UUID, data: bytes, mime_type: str) -> ImageReference:
        try:
            metadata = await validate_image(
                bytes(data),
                mime_type,
                self.settings.max_image_bytes,
                self.settings.max_image_pixels,
            )
        except ValueError:
            raise ServiceError("INVALID_IMAGE", "Unsupported or invalid image", 422) from None
        image = ImageReference(image_id=uuid4(), metadata=metadata)
        async with self.store.client.transaction(write=True) as tx:
            exists = await tx.fetchval(
                "SELECT session_id FROM app_session WHERE session_id=$1 FOR UPDATE", sid
            )
            if exists is None:
                raise ServiceError("NOT_FOUND", "Conversation not found", 404)
            count = await tx.fetchval("SELECT count(*) FROM chat_image WHERE session_id=$1", sid)
            if count >= self.settings.max_session_images:
                raise ServiceError("UPLOAD_LIMIT", "Session image limit reached", 409)
            await tx.execute(
                "INSERT INTO chat_image(image_id,session_id,metadata,content) "
                "VALUES($1,$2,$3::jsonb,$4)",
                image.image_id,
                sid,
                image.model_dump_json(),
                bytes(data),
            )
        return image
