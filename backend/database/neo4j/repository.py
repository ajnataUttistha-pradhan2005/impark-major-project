from typing import Protocol

from backend.contracts.agents import GraphAgentInput, GraphAgentOutput


class GraphRepository(Protocol):
    """Map allow-listed intent to parameterized Cypher; enforce read-only timeout/limit."""

    async def retrieve(self, request: GraphAgentInput) -> GraphAgentOutput: ...
