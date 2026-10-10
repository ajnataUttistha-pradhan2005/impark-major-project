"""One asynchronous pool; explicit bounded transactions and safe errors."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from backend.database.search_config import SearchSettings


class StoreError(RuntimeError):
    def __init__(self, code: str = "UNAVAILABLE") -> None:
        self.code = code
        super().__init__(f"Search store operation failed: {code}")


class PostgresClient:
    def __init__(self, config: SearchSettings) -> None:
        self.config = config
        self.pool: Any = None

    async def open(self) -> None:
        if self.pool is not None:
            return
        if not self.config.database_url:
            raise StoreError("CONFIGURATION")
        try:
            self.pool = await asyncpg.create_pool(
                self.config.database_url.get_secret_value(),
                min_size=1,
                max_size=self.config.postgres_pool_size,
                timeout=self.config.store_timeout_seconds,
                command_timeout=self.config.store_timeout_seconds,
            )
        except (asyncpg.PostgresError, OSError, TimeoutError, ValueError):
            raise StoreError("CONNECTIVITY") from None

    async def close(self) -> None:
        if self.pool is not None:
            try:
                async with asyncio.timeout(self.config.store_timeout_seconds):
                    await self.pool.close()
            finally:
                self.pool.terminate()
                self.pool = None

    @asynccontextmanager
    async def transaction(self, *, write: bool = False) -> AsyncIterator[Any]:
        if self.pool is None:
            raise StoreError("CLOSED")
        try:
            async with asyncio.timeout(self.config.store_timeout_seconds):
                async with self.pool.acquire() as connection:
                    async with connection.transaction(readonly=not write):
                        yield connection
        except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
            code = "TIMEOUT" if isinstance(exc, TimeoutError) else "QUERY"
            raise StoreError(code) from None

    async def read(self, sql: str, *parameters: object) -> list[dict[str, Any]]:
        async with self.transaction() as tx:
            rows: list[dict[str, Any]] = []
            async for row in tx.cursor(sql, *parameters):
                if len(rows) >= self.config.store_max_records:
                    raise StoreError("RESULT_LIMIT")
                rows.append(dict(row))
            return rows

    async def write(self, sql: str, *parameters: object) -> list[dict[str, Any]]:
        async with self.transaction(write=True) as tx:
            return [dict(row) for row in await tx.fetch(sql, *parameters)]

    async def single(self, sql: str, *parameters: object) -> dict[str, Any] | None:
        rows = await self.read(sql, *parameters)
        if len(rows) > 1:
            raise StoreError("CARDINALITY")
        return rows[0] if rows else None

    async def scalar(self, sql: str, *parameters: object) -> Any:
        row = await self.single(sql, *parameters)
        if row is None:
            return None
        if len(row) != 1:
            raise StoreError("CARDINALITY")
        return next(iter(row.values()))

    async def health(self) -> bool:
        return bool(await self.scalar("SELECT 1") == 1)
