"""Explicit local response-model integration, including the durable SSE contract."""

import asyncio
import json
import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest

from backend.config.settings import Settings
from backend.main import create_app

pytestmark = pytest.mark.skipif(os.getenv("OLLAMA_RUN_INTEGRATION") != "1", reason="Local opt-in")


async def test_graph_to_guarded_ollama_to_replayable_sse():
    settings = Settings(
        image_enabled=False,
        llm_provider="ollama",
        text_semantic_enabled=False,
        enable_development_api=True,
        api_key=None,
    )
    assert settings.application_env == "development"
    assert urlsplit(settings.database_url.get_secret_value()).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(settings.neo4j_uri).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(settings.ollama_base_url or "").hostname in {"localhost", "127.0.0.1"}
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post("/api/v1/conversations", json={})
            assert created.status_code == 201, created.text
            sid = created.json()["session_id"]
            try:
                oid = uuid4()
                accepted = await client.post(
                    f"/api/v1/conversations/{sid}/turns",
                    json={"request_id": str(oid), "text": "What phytochemicals are in neem?"},
                )
                assert accepted.status_code == 202, accepted.text
                await asyncio.wait_for(app.state.runs.tasks[oid], 60)
                run = (await client.get(f"/api/v1/runs/{oid}")).json()
                assert run["status"] == "complete", run
                result = run["result"]
                assert result["status"] == "COMPLETE" and result["mode"] == "conversation"
                answer = result["response"]
                assert answer["provider"] == "ollama" and not answer["fallback_used"]
                assert answer["citation_ids"]
                assert "Educational use only" in answer["text"]
                evidence = (await client.get(f"/api/v1/runs/{oid}/evidence")).json()["items"]
                assert set(answer["citation_ids"]) <= {e["evidence_id"] for e in evidence}
                stream = await client.get(f"/api/v1/runs/{oid}/events")
                events = [
                    json.loads(line[6:])
                    for line in stream.text.splitlines()
                    if line.startswith("data: ")
                ]
                assert events[-1]["type"] == "run_completed"
                assert (
                    "".join(e["payload"]["text"] for e in events if e["type"] == "response_delta")
                    == answer["text"]
                )
            finally:
                await app.state.runs.delete(UUID(sid))
