from backend.contracts.actions import Capability
from backend.contracts.agents import GraphAgentInput, GraphAgentOutput, Observation


class GraphAgent:
    """TODO: inject read-only Neo4j provider; never accept Cypher or produce prose."""

    async def execute(self, request: GraphAgentInput) -> Observation:
        return Observation(
            invocation=request.invocation,
            component=Capability.GRAPH,
            payload=GraphAgentOutput(),
        )
