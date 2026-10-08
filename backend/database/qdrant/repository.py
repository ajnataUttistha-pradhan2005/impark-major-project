from typing import Protocol

from backend.contracts.agents import CandidatePlant


class VectorRepository(Protocol):
    """TODO R-009: dimensions/metric/collection; adapters must validate them."""

    async def search(self, embedding: list[float], limit: int) -> list[CandidatePlant]: ...
