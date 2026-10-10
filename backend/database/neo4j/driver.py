"""One pooled async driver per application lifecycle; sessions belong to operations."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from neo4j import READ_ACCESS, WRITE_ACCESS, AsyncDriver, AsyncGraphDatabase, AsyncSession
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired

from backend.database.neo4j.config import Neo4jConfig
from backend.database.neo4j.errors import GraphDatabaseError, translate_error

logger = logging.getLogger(__name__)
DriverFactory = Callable[[Neo4jConfig], AsyncDriver]


def create_driver(config: Neo4jConfig) -> AsyncDriver:
    # Encryption/routing are selected solely by the URI. Never override Aura TLS settings.
    return AsyncGraphDatabase.driver(
        config.uri,
        auth=(config.username.get_secret_value(), config.password.get_secret_value()),
        connection_timeout=config.connection_timeout_seconds,
        connection_acquisition_timeout=config.acquisition_timeout_seconds,
        max_connection_pool_size=config.max_pool_size,
        max_transaction_retry_time=0,  # Harness owns retries; no hidden multiplying retry loop.
    )


class Neo4jConnection:
    def __init__(self, config: Neo4jConfig, factory: DriverFactory = create_driver) -> None:
        self.config = config
        self._factory = factory
        self._driver: AsyncDriver | None = None
        self._lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        return self._driver is not None

    async def server_info(self) -> dict[str, str]:
        if self._driver is None:
            raise GraphDatabaseError("NOT_OPEN", "Neo4j connection is not open")
        try:
            info = await self._driver.get_server_info()
            return {"agent": info.agent, "protocol_version": str(info.protocol_version)}
        except (Neo4jError, ServiceUnavailable, SessionExpired, OSError, TimeoutError) as exc:
            raise translate_error(exc) from None

    async def open(self) -> None:
        async with self._lock:
            if self._driver is not None:
                return
            driver = self._factory(self.config)
            try:
                await driver.verify_connectivity()
                # Also verify configured database selection and read permission.
                async with driver.session(
                    database=self.config.database, default_access_mode=READ_ACCESS
                ) as session:
                    from neo4j import Query

                    result = await session.run(
                        Query("RETURN 1 AS ok", timeout=self.config.transaction_timeout_seconds)
                    )
                    await result.consume()
            except (Neo4jError, ServiceUnavailable, SessionExpired, OSError, TimeoutError) as exc:
                await driver.close()
                error = translate_error(exc)
                logger.warning("neo4j_start_failed code=%s", error.code)
                raise error from None
            except BaseException:
                await driver.close()
                raise
            self._driver = driver
            logger.info("neo4j_connected")

    @asynccontextmanager
    async def session(self, *, write: bool = False) -> AsyncIterator[AsyncSession]:
        if self._driver is None:
            raise GraphDatabaseError("NOT_OPEN", "Neo4j connection is not open")
        if write and not self.config.allow_writes:
            raise GraphDatabaseError("WRITES_DISABLED", "Neo4j writes are disabled")
        async with self._driver.session(
            database=self.config.database,
            default_access_mode=WRITE_ACCESS if write else READ_ACCESS,
            fetch_size=min(1000, self.config.max_result_records),
        ) as session:
            yield session

    async def close(self) -> None:
        async with self._lock:
            driver, self._driver = self._driver, None
            if driver is not None:
                await driver.close()
                logger.info("neo4j_closed")

    async def __aenter__(self) -> "Neo4jConnection":
        await self.open()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
