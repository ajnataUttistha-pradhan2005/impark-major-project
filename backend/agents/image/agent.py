from backend.agents.image.providers import ImageInferenceProvider
from backend.contracts.actions import Capability
from backend.contracts.agents import ImageAgentInput, ImageAgentResult, Observation


class ImageAgent:
    """Image capability adapter. All global state changes remain with the harness."""

    def __init__(self, provider: ImageInferenceProvider | None = None) -> None:
        self.provider = provider

    async def execute(self, request: ImageAgentInput) -> Observation:
        result = (
            await self.provider.infer(request.image, request.invocation.correlation.session_id)
            if self.provider
            else ImageAgentResult()
        )
        return Observation(
            invocation=request.invocation,
            component=Capability.IMAGE,
            payload=result,
        )
