from backend.contracts.actions import Capability
from backend.contracts.agents import (
    Failure,
    FailureType,
    GraphAgentInput,
    GraphAgentOutput,
    Observation,
)
from backend.database.neo4j.errors import GraphDatabaseError
from backend.database.neo4j.repository import GraphRepository
from backend.database.postgres.client import StoreError


class GraphAgent:
    """Only typed requests reach the allow-listed graph retrieval adapter."""

    def __init__(self, repository: GraphRepository | None = None) -> None:
        self.repository = repository

    async def execute(self, request: GraphAgentInput) -> Observation | Failure:
        try:
            request = GraphAgentInput.model_validate(request.model_dump(mode="python"))
        except ValueError:
            return Failure(
                invocation=request.invocation,
                error_type=FailureType.INVALID_INPUT,
                reason="Invalid typed graph request",
            )
        try:
            payload = (
                await self.repository.retrieve(request) if self.repository else GraphAgentOutput()
            )
        except GraphDatabaseError as error:
            return Failure(
                invocation=request.invocation,
                error_type=FailureType.TIMEOUT
                if error.code == "TIMEOUT"
                else (
                    FailureType.DEPENDENCY_UNAVAILABLE if error.retryable else FailureType.PERMANENT
                ),
                reason="Graph evidence unavailable",
                retryable=error.retryable,
            )
        except StoreError:
            return Failure(
                invocation=request.invocation,
                error_type=FailureType.DEPENDENCY_UNAVAILABLE,
                reason="Graph evidence unavailable",
                retryable=True,
            )
        return Observation(
            invocation=request.invocation,
            component=Capability.GRAPH,
            payload=payload,
        )
