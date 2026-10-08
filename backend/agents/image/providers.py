from typing import Protocol

from backend.contracts.agents import ImageAgentResult, ImageReference


class ImageInferenceProvider(Protocol):
    """Future pretrained custom CNN model; CPU/GPU execution must be off-loop."""

    async def infer(self, image: ImageReference) -> ImageAgentResult: ...
