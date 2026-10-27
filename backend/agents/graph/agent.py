import time
from typing import Any

from backend.agents.common.callbacks import emit_agent_end, emit_agent_error, emit_agent_start
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

    async def execute(
        self, request: GraphAgentInput, callbacks: Any = None
    ) -> Observation | Failure:
        t_start = time.perf_counter()
        run_id = str(request.invocation.correlation.run_id)
        emit_agent_start(
            callbacks, "knowledge_graph", request.query.query_type.value, run_id=run_id
        )

        try:
            request = GraphAgentInput.model_validate(request.model_dump(mode="python"))
        except ValueError as err:
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            emit_agent_error(
                callbacks, "knowledge_graph", err, run_id=run_id, latency_ms=elapsed_ms
            )
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
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            emit_agent_error(
                callbacks, "knowledge_graph", error, run_id=run_id, latency_ms=elapsed_ms
            )
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
        except StoreError as error:
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            emit_agent_error(
                callbacks, "knowledge_graph", error, run_id=run_id, latency_ms=elapsed_ms
            )
            return Failure(
                invocation=request.invocation,
                error_type=FailureType.DEPENDENCY_UNAVAILABLE,
                reason="Graph evidence unavailable",
                retryable=True,
            )

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        context_snippets = [e.claim for e in payload.evidence] if payload.evidence else []
        emit_agent_end(
            callbacks,
            "knowledge_graph",
            payload,
            run_id=run_id,
            latency_ms=elapsed_ms,
            context_snippets=context_snippets,
        )

        return Observation(
            invocation=request.invocation,
            component=Capability.GRAPH,
            payload=payload,
        )
