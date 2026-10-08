from backend.agents.text.providers import EntitySearchProvider
from backend.agents.text.resolver import normalize
from backend.contracts.actions import Capability
from backend.contracts.agents import Observation, TextAgentInput, TextResult


class TextAgent:
    def __init__(self, provider: EntitySearchProvider | None = None) -> None:
        self.provider = provider

    async def execute(self, request: TextAgentInput) -> Observation:
        candidates = (
            await self.provider.search(normalize(request.text), limit=5) if self.provider else []
        )
        return Observation(
            invocation=request.invocation,
            component=Capability.TEXT,
            payload=TextResult(candidates=candidates, placeholder=self.provider is None),
            confidence=max((c.confidence for c in candidates), default=0),
        )
