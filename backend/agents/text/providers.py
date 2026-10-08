from typing import Protocol

from backend.contracts.agents import CandidatePlant


class EntitySearchProvider(Protocol):
    """Implement exact/alias -> FTS -> trigram/fuzzy -> semantic behind this port."""

    async def search(self, normalized_text: str, limit: int) -> list[CandidatePlant]: ...


class EntityDisambiguator(Protocol):
    """Future bounded final-step disambiguation among supplied candidates only."""

    async def disambiguate(
        self, text: str, candidates: list[CandidatePlant]
    ) -> list[CandidatePlant]: ...


class EntityExtractor(Protocol):
    async def extract(self, text: str) -> list[str]: ...


class CoreferenceResolver(Protocol):
    async def resolve(self, text: str, active: CandidatePlant | None) -> str | None: ...
