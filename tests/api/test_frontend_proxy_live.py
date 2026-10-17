"""Opt-in, reversible smoke test through the running Next.js API proxy."""

import asyncio
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CHAT_HTTP_INTEGRATION") != "1", reason="Local opt-in"
)


async def test_discovery_followup_and_exact_sources_via_frontend_proxy() -> None:
    base = os.getenv("FRONTEND_URL", "http://127.0.0.1:3000")
    assert urlsplit(base).hostname in {"127.0.0.1", "localhost"}
    async with httpx.AsyncClient(base_url=base, timeout=20, trust_env=False) as client:
        capabilities = await client.get("/api/v1/capabilities")
        capabilities.raise_for_status()
        assert capabilities.json()["one_plant_per_session"]
        created = await client.post(
            "/api/v1/conversations", json={"title": "Temporary explanation smoke test"}
        )
        created.raise_for_status()
        sid = created.json()["session_id"]

        async def turn(question: str) -> dict:
            oid = str(uuid4())
            response = await client.post(
                f"/api/v1/conversations/{sid}/turns",
                json={"request_id": oid, "text": question},
            )
            response.raise_for_status()
            for _ in range(180):
                status = (await client.get(f"/api/v1/runs/{oid}")).json()
                if status["status"] in {"complete", "failed", "cancelled"}:
                    assert status["status"] == "complete", status
                    return status
                await asyncio.sleep(0.5)
            raise AssertionError("Run did not finish in 90 seconds")

        try:
            identified = await turn("Basella alba")
            plant = identified["result"]["active_plant"]
            assert identified["result"]["mode"] == "conversation"
            assert plant["label"] == "Basella alba"
            listed = await turn("List the phytochemicals")
            assert listed["result"]["active_plant"]["plant_id"] == plant["plant_id"]
            assert listed["result"]["response"]["citation_ids"]
            explained = await turn("Explain each of them")
            result = explained["result"]
            assert result["active_plant"]["plant_id"] == plant["plant_id"]
            answer = result["response"]["text"]
            if os.getenv("RESPONSE_CAPTURE_OUTPUT") == "1":
                print(
                    "\nexplanation response:"
                    f" provider={result['response']['provider']}"
                    f" fallback={result['response']['fallback_used']}\n{answer}"
                )
            assert "choose a plant" not in answer.casefold()
            assert "graph" not in answer.casefold()
            cited = result["response"]["citation_ids"]
            assert cited
            evidence = await client.get(f"/api/v1/runs/{explained['operation_id']}/evidence")
            evidence.raise_for_status()
            assert set(cited) <= {item["evidence_id"] for item in evidence.json()["items"]}
            history = await client.get(f"/api/v1/conversations/{sid}/messages")
            history.raise_for_status()
            assert len(history.json()["items"]) == 6
        finally:
            deleted = await client.delete(f"/api/v1/conversations/{sid}")
            assert deleted.status_code == 204
