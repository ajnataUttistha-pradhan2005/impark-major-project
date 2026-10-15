from typing import Protocol
from uuid import UUID

from backend.contracts.agents import ImageAgentResult, ImageReference


class ImageInferenceProvider(Protocol):
    """Bounded model/retrieval provider; image access is always session-scoped."""

    async def infer(self, image: ImageReference, session_id: UUID) -> ImageAgentResult: ...
