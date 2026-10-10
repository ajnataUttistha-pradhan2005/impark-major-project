import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from neo4j.exceptions import AuthError, ServiceUnavailable
from pydantic import SecretStr

from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import Neo4jConfig
from backend.database.neo4j.driver import Neo4jConnection, create_driver
from backend.database.neo4j.errors import GraphDatabaseError


class Result:
    def __init__(self, rows, query_type="r"):
        self.rows = rows
        self.query_type = query_type

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row

        return iterate()

    async def consume(self):
        return SimpleNamespace(query_type=self.query_type)


@pytest.fixture
def rig():
    config = Neo4jConfig(
        uri="bolt://test.invalid:7687",
        username=SecretStr("fixture"),
        password=SecretStr("private-fixture"),
        database="fixture",
        allow_writes=True,
    )
    tx = MagicMock()
    tx.run = AsyncMock(return_value=Result([{"answer": 42}]))
    tx.commit = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.run = AsyncMock(return_value=Result([{"ok": 1}]))
    session.begin_transaction = AsyncMock(return_value=tx)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    driver = MagicMock()
    driver.verify_connectivity = AsyncMock()
    driver.session.return_value = session
    driver.close = AsyncMock()
    factory = MagicMock(return_value=driver)
    connection = Neo4jConnection(config, factory)
    return SimpleNamespace(
        connection=connection,
        driver=driver,
        tx=tx,
        session=session,
        factory=factory,
        client=Neo4jClient(connection),
    )


async def test_lifecycle_reuses_single_driver_and_closes_sessions(rig):
    async with rig.connection:
        await rig.connection.open()
        assert await rig.client.scalar("RETURN $value AS answer", {"value": 42}) == 42
        assert await rig.client.single("RETURN $value AS answer", {"value": 42}) == {"answer": 42}
        rows = await rig.client.read("RETURN $value AS answer", {"value": 42})
        assert rows == [{"answer": 42}]
        assert rig.factory.call_count == 1
        assert rig.session.begin_transaction.await_count == 3
        assert rig.tx.commit.await_count == 3
        assert rig.driver.session.call_args.kwargs["database"] == "fixture"
    rig.driver.close.assert_awaited_once()
    await rig.connection.close()
    rig.driver.close.assert_awaited_once()


async def test_parameter_values_are_never_interpolated(rig):
    payload = "x' MATCH (n) DETACH DELETE n //"
    async with rig.connection:
        await rig.client.read("RETURN $value AS answer", {"value": payload})
    assert rig.tx.run.call_args.args == ("RETURN $value AS answer",)
    assert rig.tx.run.call_args.kwargs == {"parameters": {"value": payload}}


async def test_multiple_statements_share_transaction_and_exception_rolls_back(rig):
    async with rig.connection:
        with pytest.raises(ValueError, match="caller abort"):
            async with rig.client.transaction(write=True) as tx:
                await tx.records("RETURN 1")
                await tx.records("RETURN 2")
                raise ValueError("caller abort")
    rig.tx.commit.assert_not_awaited()
    assert rig.tx.__aexit__.call_args.args[0] is ValueError
    assert rig.session.begin_transaction.await_count == 1


async def test_cancellation_rolls_back(rig):
    async with rig.connection:
        with pytest.raises(asyncio.CancelledError):
            async with rig.client.transaction(write=True):
                raise asyncio.CancelledError()
    rig.tx.commit.assert_not_awaited()
    assert rig.tx.__aexit__.call_args.args[0] is asyncio.CancelledError


async def test_callback_transactions(rig):
    async def work(tx):
        return await tx.scalar("RETURN 42 AS answer")

    async with rig.connection:
        assert await rig.client.execute_read(work) == 42
        assert await rig.client.execute_write(work) == 42
    assert rig.tx.commit.await_count == 2


async def test_write_guard_before_session(rig):
    rig.connection.config = rig.connection.config.model_copy(update={"allow_writes": False})
    async with rig.connection:
        count = rig.driver.session.call_count
        with pytest.raises(GraphDatabaseError, match="writes are disabled"):
            await rig.client.write("CREATE ()")
        assert rig.driver.session.call_count == count


async def test_read_guard_rejects_server_classified_write(rig):
    rig.tx.run.return_value = Result([], query_type="w")
    async with rig.connection:
        with pytest.raises(GraphDatabaseError, match="non-read"):
            await rig.client.read("CREATE ()")
    assert rig.tx.run.await_count == 1
    assert rig.tx.run.call_args.args == ("EXPLAIN CREATE ()",)
    rig.tx.commit.assert_not_awaited()


async def test_safe_errors_and_logs(rig, caplog):
    rig.tx.run.side_effect = ServiceUnavailable("private-fixture bolt://secret@host RETURN private")
    async with rig.connection:
        with pytest.raises(GraphDatabaseError) as captured:
            await rig.client.read("RETURN $secret", {"secret": "private-fixture"})
    assert captured.value.code == "UNAVAILABLE"
    assert captured.value.retryable
    assert "private-fixture" not in str(captured.value)
    assert "private-fixture" not in caplog.text
    assert "RETURN" not in caplog.text


async def test_failed_connect_closes_driver(rig):
    rig.driver.verify_connectivity.side_effect = AuthError("password=private-fixture")
    with pytest.raises(GraphDatabaseError) as exc:
        await rig.connection.open()
    assert exc.value.code == "AUTHENTICATION"
    assert not rig.connection.is_open
    rig.driver.close.assert_awaited_once()


async def test_result_and_timeout_bounds(rig):
    rig.connection.config = rig.connection.config.model_copy(update={"max_result_records": 1})
    rig.tx.run.return_value = Result([{"x": 1}, {"x": 2}])
    async with rig.connection:
        with pytest.raises(GraphDatabaseError, match="record limit"):
            await rig.client.read("UNWIND [1,2] AS x RETURN x")
        with pytest.raises(ValueError):
            await rig.client.read("RETURN 1", timeout_seconds=0)
        with pytest.raises(ValueError):
            await rig.client.read("RETURN 1", timeout_seconds=999)


async def test_custom_timeout_reaches_server_transaction(rig):
    async with rig.connection:
        await rig.client.read("RETURN 42 AS answer", timeout_seconds=2.5)
    assert rig.session.begin_transaction.call_args.kwargs == {"timeout": 2.5}


async def test_timeout_error_is_safe_and_retryable(rig):
    rig.tx.run.side_effect = TimeoutError("private timeout detail")
    async with rig.connection:
        with pytest.raises(GraphDatabaseError) as exc:
            await rig.client.read("RETURN 42 AS answer")
    assert exc.value.code == "TIMEOUT"
    assert exc.value.retryable
    assert "private" not in str(exc.value)


async def test_queries_after_close_fail_cleanly(rig):
    async with rig.connection:
        pass
    with pytest.raises(GraphDatabaseError) as exc:
        await rig.client.read("RETURN 1")
    assert exc.value.code == "NOT_OPEN"


async def test_single_scalar_cardinality(rig):
    async with rig.connection:
        rig.tx.run.return_value = Result([])
        assert await rig.client.single("RETURN 1") is None
        assert await rig.client.scalar("RETURN 1") is None
        rig.tx.run.return_value = Result([{"a": 1, "b": 2}])
        with pytest.raises(GraphDatabaseError, match="scalar"):
            await rig.client.scalar("RETURN 1, 2")
        rig.tx.run.return_value = Result([{"a": 1}, {"a": 2}])
        with pytest.raises(GraphDatabaseError, match="at most one"):
            await rig.client.single("RETURN 1")


def test_driver_factory_uses_configuration_without_tls_override(rig, monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr("backend.database.neo4j.driver.AsyncGraphDatabase.driver", factory)
    for uri in ("bolt://localhost:7687", "neo4j+s://example.databases.neo4j.io"):
        config = rig.connection.config.model_copy(update={"uri": uri})
        create_driver(config)
        assert factory.call_args.args == (uri,)
        assert "encrypted" not in factory.call_args.kwargs
        assert factory.call_args.kwargs["max_transaction_retry_time"] == 0
