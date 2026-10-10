import asyncio
from uuid import uuid4

from backend.agents.text.agent import TextAgent
from backend.agents.text.search import HybridNameSearch
from tests.text.test_agent import request


async def test_cancelled_embedding_does_not_queue_more_native_workers():
    import threading

    import pytest

    from backend.agents.text.embeddings import FastEmbedProvider
    from backend.database.search_config import SearchSettings

    provider = FastEmbedProvider(SearchSettings(_env_file=None))
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def encode(texts):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(3)
        return [[1.0]]

    provider._encode = encode
    task = asyncio.create_task(provider.embed(["fixture"]))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(OSError):
            await provider.embed(["another"])
        assert calls == 1
    finally:
        release.set()
        if provider.worker:
            await provider.worker


async def test_exact_name_skips_expensive_unrelated_entity_lookup(name_search):
    async def unexpected(*args):
        raise AssertionError("Exact name must not query entity catalog, lexical or embeddings")

    name_search.repository.entities = unexpected
    name_search.repository.lexical = unexpected
    result = await TextAgent(name_search).execute(request("neem"))
    assert result.payload.candidates[0].confidence >= 0.95
    assert result.payload.stages == ["exact_alias"]


async def test_concurrent_catalog_loads_once_and_generation_refreshes(name_search):
    source = name_search.repository
    original = source.names
    calls = 0

    async def counting(generation):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.005)
        return await original(generation)

    source.names = counting
    search = HybridNameSearch(source)
    responses = await asyncio.gather(*(search.search("neem") for _ in range(30)))
    assert calls == 1
    assert all(r[0].label == "Fixture neem" for r in responses)
    source.records = [r for r in source.records if r.plant_name != "Fixture neem"]
    source.version = uuid4()
    responses = await search.search("neem")
    assert calls == 2
    assert all(r.label != "Fixture neem" for r in responses)


async def test_mutating_candidate_response_cannot_poison_catalog(name_search):
    result = await name_search.search("neem")
    result[0].label = "poisoned"
    result[0].confidence = 0
    fresh = await name_search.search("neem")
    assert fresh[0].label == "Fixture neem"
    assert fresh[0].confidence >= 0.95
