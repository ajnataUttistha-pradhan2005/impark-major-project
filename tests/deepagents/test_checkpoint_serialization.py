"""Tests verifying LangGraph checkpoint UUID serialization and normalization."""

import uuid
import warnings
from uuid import UUID

import asyncpg.pgproto.pgproto
import pytest

from backend.contracts.base import CorrelationMetadata
from backend.database.postgres.checkpoints import checkpoint_serializer
from backend.orchestrator.deepagents.graph import RuntimeState, build_deep_graph
from backend.state.models import ConversationState, TaskStatus


def test_correlation_metadata_normalizes_asyncpg_uuid():
    """Verify that driver-specific asyncpg UUIDs are coerced to standard uuid.UUID."""
    raw_str = "12345678-1234-5678-1234-567812345678"
    driver_uuid = asyncpg.pgproto.pgproto.UUID(raw_str)

    assert isinstance(driver_uuid, UUID)
    assert type(driver_uuid) is not UUID
    assert type(driver_uuid) is asyncpg.pgproto.pgproto.UUID

    meta = CorrelationMetadata(session_id=driver_uuid)
    assert type(meta.session_id) is UUID
    assert str(meta.session_id) == raw_str


def test_conversation_state_normalizes_session_id():
    """Verify that ConversationState correlation session_id uses normalized UUID."""
    raw_str = "abcdef01-2345-6789-abcd-ef0123456789"
    driver_uuid = asyncpg.pgproto.pgproto.UUID(raw_str)

    state = ConversationState.new()
    state.correlation.session_id = driver_uuid

    assert type(state.correlation.session_id) is UUID
    assert str(state.correlation.session_id) == raw_str


def test_checkpoint_serializer_restores_legacy_asyncpg_uuid_without_warning():
    """Verify legacy checkpoints with asyncpg UUID deserialize without warning."""
    serializer = checkpoint_serializer()
    raw_str = "abcdef01-2345-6789-abcd-ef0123456789"
    driver_uuid = asyncpg.pgproto.pgproto.UUID(raw_str)

    # Serialize using the underlying msgpack encoder with the driver-specific UUID
    type_name, blob = serializer.dumps_typed(driver_uuid)
    assert type_name == "msgpack"

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        restored = serializer.loads_typed((type_name, blob))

        # Check that no deserialization warnings were triggered
        serde_warnings = [
            str(w.message)
            for w in recorded
            if "allowed_msgpack_modules" in str(w.message) or "asyncpg" in str(w.message)
        ]
        assert not serde_warnings, f"Unexpected serde warnings: {serde_warnings}"

    assert str(restored) == raw_str


def test_new_graph_state_roundtrip_uses_standard_uuid():
    """Verify new graph state serializes cleanly with standard UUID and zero warnings."""
    serializer = checkpoint_serializer()
    state = ConversationState.new()
    state.user_message = "What are the medicinal properties of Tulsi?"

    type_name, blob = serializer.dumps_typed({"domain": state})

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        restored = serializer.loads_typed((type_name, blob))

        serde_warnings = [
            str(w.message)
            for w in recorded
            if "allowed_msgpack_modules" in str(w.message) or "asyncpg" in str(w.message)
        ]
        assert not serde_warnings

    restored_domain = restored["domain"]
    assert type(restored_domain.correlation.session_id) is UUID
    assert restored_domain.user_message == state.user_message


@pytest.mark.asyncio
async def test_restore_persisted_legacy_checkpoint_from_db():
    """Verify existing legacy checkpoint from PostgreSQL restores without warning."""
    import asyncpg

    from backend.config.settings import Settings

    settings = Settings()
    if not settings.database_url:
        pytest.skip("PostgreSQL not configured")

    serializer = checkpoint_serializer()
    conn = await asyncpg.connect(settings.database_url.get_secret_value())
    try:
        row = await conn.fetchrow(
            "SELECT thread_id, channel, type, blob FROM checkpoint_blobs "
            "WHERE position('asyncpg'::bytea in blob) > 0 LIMIT 1"
        )
        if not row:
            pytest.skip("No existing legacy asyncpg checkpoint blobs found in database")

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            restored = serializer.loads_typed((row["type"], row["blob"]))

            serde_warnings = [
                str(w.message)
                for w in recorded
                if "allowed_msgpack_modules" in str(w.message) or "asyncpg" in str(w.message)
            ]
            assert not serde_warnings, f"Serde warning on legacy checkpoint: {serde_warnings}"

        assert isinstance(restored, ConversationState)
        assert str(restored.correlation.session_id)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_minimal_graph_checkpoint_roundtrip_with_saver():
    """Verify minimal roundtrip through AsyncPostgresSaver if Postgres is available."""
    from backend.config.settings import Settings

    settings = Settings()
    if not settings.database_url:
        pytest.skip("PostgreSQL not configured")

    from backend.database.postgres.checkpoints import checkpoints

    class MockRuntime:
        async def run(self, state: ConversationState) -> ConversationState:
            state.termination.status = TaskStatus.COMPLETE
            return state

    try:
        async with checkpoints(settings) as saver:
            graph = build_deep_graph(MockRuntime(), saver)
            thread_id = str(uuid.uuid4())
            run_config = {"configurable": {"thread_id": thread_id}}

            state = ConversationState.new()
            # Even if driver_uuid was somehow assigned, graph state stays normalized
            driver_uuid = asyncpg.pgproto.pgproto.UUID(str(state.correlation.session_id))
            state.correlation.session_id = driver_uuid
            assert type(state.correlation.session_id) is UUID

            with warnings.catch_warnings(record=True) as recorded:
                warnings.simplefilter("always")
                result = await graph.ainvoke(RuntimeState(domain=state), run_config)
                assert result["domain"].termination.status == TaskStatus.COMPLETE

                checkpoint_state = await graph.aget_state(run_config)
                assert checkpoint_state.values

                restored = checkpoint_state.values["domain"]
                assert type(restored.correlation.session_id) is UUID
                assert restored.correlation.session_id == state.correlation.session_id

                serde_warnings = [
                    str(w.message)
                    for w in recorded
                    if "allowed_msgpack_modules" in str(w.message) or "asyncpg" in str(w.message)
                ]
                assert not serde_warnings

            await saver.adelete_thread(thread_id)
    except Exception as exc:
        if "InterfaceError" in type(exc).__name__:
            pytest.skip("psycopg requires SelectorEventLoop on Windows")
        raise
