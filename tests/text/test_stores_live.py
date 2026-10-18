"""Opt-in local tests: SEARCH_RUN_INTEGRATION=1; no production test writes."""

import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from backend.agents.text.embeddings import FastEmbedProvider
from backend.agents.text.search import HybridNameSearch
from backend.database.postgres.client import PostgresClient, StoreError
from backend.database.postgres.migrate import migrate
from backend.database.postgres.search import PostgresNameRepository
from backend.database.qdrant.client import QdrantStore
from backend.database.search_config import SearchSettings

pytestmark = pytest.mark.skipif(
    os.getenv("SEARCH_RUN_INTEGRATION") != "1", reason="Explicit local opt-in"
)


@pytest_asyncio.fixture
async def stores():
    config = SearchSettings()
    assert urlsplit(config.database_url.get_secret_value()).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(config.qdrant_url).hostname in {"localhost", "127.0.0.1"}
    postgres = PostgresClient(config)
    vectors = QdrantStore(config)
    await postgres.open()
    try:
        yield postgres, vectors, config
    finally:
        await vectors.close()
        await postgres.close()


async def test_connectivity_and_parameterization(stores):
    postgres, vectors, _ = stores
    assert await postgres.health()
    assert await vectors.health()
    injected = "'; DROP TABLE search_plant; --"
    assert await postgres.scalar("SELECT $1::text", injected) == injected


async def test_transactions_and_read_guard(stores):
    postgres, _, _ = stores
    identifier = uuid4()
    with pytest.raises(RuntimeError, match="rollback"):
        async with postgres.transaction(write=True) as tx:
            await tx.execute(
                "INSERT INTO app_session(session_id,state) VALUES($1,'{}')", identifier
            )
            raise RuntimeError("rollback")
    assert (
        await postgres.scalar("SELECT count(*) FROM app_session WHERE session_id=$1", identifier)
        == 0
    )
    with pytest.raises(StoreError):
        await postgres.read("INSERT INTO app_session(session_id,state) VALUES($1,'{}')", identifier)
    async with postgres.transaction(write=True) as tx:
        await tx.execute("INSERT INTO app_session(session_id,state) VALUES($1,'{}')", identifier)
        assert (
            await tx.fetchval("SELECT count(*) FROM app_session WHERE session_id=$1", identifier)
            == 1
        )
        await tx.execute("DELETE FROM app_session WHERE session_id=$1", identifier)


async def test_repeatable_migration_and_catalog(stores):
    postgres, vectors, _ = stores
    await migrate(postgres)
    await migrate(postgres)
    repo = PostgresNameRepository(postgres)
    generation = await repo.generation()
    records = await repo.names(generation)
    assert len({r.plant_id for r in records}) == 40
    assert len(records) == 521
    assert await vectors.count(generation) == len(records)
    assert all(r.source_key for r in records)


async def test_semantic_retrieval_actual_embedding(stores):
    postgres, vectors, config = stores
    embed = FastEmbedProvider(config)
    query = (await embed.embed(["holy basil"]))[0]
    hits = await vectors.search(await PostgresNameRepository(postgres).generation(), query, 10)
    assert any(h.record.plant_name == "Ocimum tenuiflorum" for h in hits[:5])


async def test_all_aliases_match_their_source(stores):
    postgres, _, _ = stores
    repo = PostgresNameRepository(postgres)
    records = await repo.names(await repo.generation())
    search = HybridNameSearch(repo)
    for record in records:
        candidates = await search.search(record.name, 20)
        assert str(record.plant_id) in {c.plant_id for c in candidates}, record.name


async def test_live_api_discovery_graph_and_comparison(stores):
    from backend.config.settings import Settings
    from backend.main import create_app

    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            sid = (await c.post("/dev/conversations")).json()["correlation"]["session_id"]
            for query in [
                "Which compounds are in neem leaves?",
                "What are its uses?",
                "Show bioactivity for neem",
                "Show evidence for neem",
                "Sources for neem",
            ]:
                response = await c.post(f"/dev/conversations/{sid}/turns", json={"text": query})
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["status"] == "COMPLETE", body
                assert body["response"]["citation_ids"]
                assert not body["response"]["placeholder"]
            citation = body["response"]["citation_ids"][0]
            traced = await c.post(
                f"/dev/conversations/{sid}/turns", json={"text": f"Trace evidence {citation}"}
            )
            assert traced.json()["status"] == "COMPLETE", traced.text
            assert traced.json()["response"]["citation_ids"] == [citation]
            assert "Source path:" in traced.json()["response"]["text"]
            for query in [
                "Compare neem and tulsi",
                "Which plants contain quercetin?",
                "Which plants are used for fever?",
                "Tell me about tulsi",
            ]:
                rejected = await c.post(f"/dev/conversations/{sid}/turns", json={"text": query})
                assert rejected.json()["status"] == "SCOPE_REJECTED", rejected.text
                assert "new chat" in rejected.json()["response"]["text"]
            response = await c.post(
                f"/dev/conversations/{sid}/turns", json={"text": "What dosage should I take?"}
            )
            assert response.json()["status"] == "SAFETY_ABSTENTION"
