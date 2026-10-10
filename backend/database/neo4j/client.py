"""Trusted backend Cypher API. Never expose query text through user/agent transports."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, TypeVar

from neo4j import AsyncTransaction
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from backend.database.neo4j.driver import Neo4jConnection
from backend.database.neo4j.errors import GraphDatabaseError, translate_error

RecordData = dict[str, Any]  # Native Neo4j property types are retained at this infrastructure port.
Parameters = Mapping[str, Any]
T = TypeVar("T")
logger = logging.getLogger(__name__)


class GraphTransaction:
    """Results are fully consumed within the transaction; no lazy cursor can escape."""

    def __init__(self, transaction: AsyncTransaction, max_records: int, *, read_only: bool) -> None:
        self._transaction = transaction
        self._max_records = max_records
        self._read_only = read_only

    async def records(self, cypher: str, parameters: Parameters | None = None) -> list[RecordData]:
        if not cypher.strip():
            raise ValueError("Cypher must be non-empty")
        params = dict(parameters or {})
        if any(not isinstance(key, str) for key in params):
            raise ValueError("Cypher parameter keys must be strings")
        if self._read_only:
            # READ_ACCESS is a routing hint, not authorization. Have the server classify
            # trusted Cypher before executing it; no fragile keyword blacklist.
            plan = await self._transaction.run("EXPLAIN " + cypher, parameters=params)
            summary = await plan.consume()
            if summary.query_type != "r":
                raise GraphDatabaseError("READ_ONLY", "Read operation rejected a non-read query")
        result = await self._transaction.run(cypher, parameters=params)
        rows: list[RecordData] = []
        async for record in result:
            if len(rows) >= self._max_records:
                raise GraphDatabaseError(
                    "RESULT_LIMIT", "Neo4j result exceeds configured record limit"
                )
            rows.append(dict(record))
        await result.consume()
        return rows

    async def single(self, cypher: str, parameters: Parameters | None = None) -> RecordData | None:
        rows = await self.records(cypher, parameters)
        if len(rows) > 1:
            raise GraphDatabaseError("CARDINALITY", "Expected at most one Neo4j record")
        return rows[0] if rows else None

    async def scalar(self, cypher: str, parameters: Parameters | None = None) -> Any:
        row = await self.single(cypher, parameters)
        if row is None:
            return None
        if len(row) != 1:
            raise GraphDatabaseError("CARDINALITY", "Expected one scalar column")
        return next(iter(row.values()))


class Neo4jClient:
    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    @asynccontextmanager
    async def transaction(
        self,
        *,
        write: bool = False,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[GraphTransaction]:
        seconds = (
            self._connection.config.transaction_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if not 0 < seconds <= self._connection.config.transaction_timeout_seconds:
            raise ValueError("Transaction timeout must be positive and within the configured bound")
        started = perf_counter()
        try:
            async with self._connection.session(write=write) as session:
                async with await session.begin_transaction(timeout=seconds) as transaction:
                    yield GraphTransaction(
                        transaction, self._connection.config.max_result_records, read_only=not write
                    )
                    await transaction.commit()
                    # Exceptions/cancellation before commit trigger rollback on context exit.
        except (Neo4jError, ServiceUnavailable, SessionExpired, OSError, TimeoutError) as exc:
            error = translate_error(exc)
            logger.warning(
                "neo4j_transaction_failed mode=%s code=%s", "write" if write else "read", error.code
            )
            raise error from None
        finally:
            logger.info(
                "neo4j_transaction_finished mode=%s latency_ms=%.2f",
                "write" if write else "read",
                (perf_counter() - started) * 1000,
            )

    async def read(
        self,
        cypher: str,
        parameters: Parameters | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> list[RecordData]:
        async with self.transaction(timeout_seconds=timeout_seconds) as tx:
            return await tx.records(cypher, parameters)

    async def write(
        self,
        cypher: str,
        parameters: Parameters | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> list[RecordData]:
        async with self.transaction(write=True, timeout_seconds=timeout_seconds) as tx:
            return await tx.records(cypher, parameters)

    async def single(
        self,
        cypher: str,
        parameters: Parameters | None = None,
        *,
        write: bool = False,
    ) -> RecordData | None:
        async with self.transaction(write=write) as tx:
            return await tx.single(cypher, parameters)

    async def scalar(
        self,
        cypher: str,
        parameters: Parameters | None = None,
        *,
        write: bool = False,
    ) -> Any:
        async with self.transaction(write=write) as tx:
            return await tx.scalar(cypher, parameters)

    async def execute_read(self, work: Callable[[GraphTransaction], Awaitable[T]]) -> T:
        async with self.transaction() as tx:
            return await work(tx)

    async def execute_write(self, work: Callable[[GraphTransaction], Awaitable[T]]) -> T:
        async with self.transaction(write=True) as tx:
            return await work(tx)

    async def health(self) -> bool:
        return bool(await self.scalar("RETURN 1 AS ok") == 1)

    async def server_info(self) -> dict[str, str]:
        return await self._connection.server_info()
