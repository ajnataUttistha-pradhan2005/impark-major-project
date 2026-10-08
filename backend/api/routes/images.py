from uuid import UUID

from fastapi import APIRouter, Depends, Request

from backend.api.dependencies.services import authorize_development
from backend.api.routes.conversations import Service
from backend.contracts.agents import ImageReference
from backend.services.errors import ServiceError
from backend.services.images import register_image

router = APIRouter(prefix="/dev", dependencies=[Depends(authorize_development)])


@router.post("/conversations/{session_id}/images", response_model=ImageReference, status_code=201)
async def upload(session_id: UUID, request: Request, service: Service) -> ImageReference:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > service.settings.max_image_bytes:
            raise ServiceError("INVALID_INPUT", "Image is too large", 413)
        content.extend(chunk)
    return await register_image(
        service,
        session_id,
        bytes(content),
        request.headers.get("content-type", ""),
    )
