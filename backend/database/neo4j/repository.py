from typing import Protocol

from backend.contracts.agents import GraphAgentOutput, GraphQuery


class GraphRepository(Protocol):
    """Map allow-listed intent to parameterized Cypher; enforce read-only timeout/limit."""

    async def retrieve(self, query: GraphQuery) -> GraphAgentOutput: ...
