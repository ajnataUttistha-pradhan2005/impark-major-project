"""Explicit local integration using supplied CNN and real image references."""

import asyncio
import io
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from PIL import Image

from backend.config.settings import Settings
from backend.main import create_app

pytestmark = pytest.mark.skipif(os.getenv("IMAGE_RUN_INTEGRATION") != "1", reason="Local opt-in")


@pytest_asyncio.fixture
async def image_api():
    settings = Settings(
        image_enabled=True,
        llm_provider="grounded",
        text_semantic_enabled=False,
        enable_development_api=True,
        api_key=None,
    )
    assert urlsplit(settings.database_url.get_secret_value()).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(settings.qdrant_url).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(settings.neo4j_uri).hostname in {"localhost", "127.0.0.1"}
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/conversations", json={"title": "Image integration test"}
            )
            assert created.status_code == 201, created.text
            sid = created.json()["session_id"]
            try:
                yield client, app.state.runs, sid
            finally:
                rows = await app.state.postgres.read(
                    "SELECT operation_id FROM api_operation WHERE session_id=$1 "
                    "AND status IN ('accepted','running','interrupted')",
                    UUID(sid),
                )
                for row in rows:
                    await app.state.runs.cancel(row["operation_id"])
                await app.state.runs.delete(UUID(sid))


async def upload(client, sid, species="Azadirachta indica", bad=False):
    if bad:
        stream = io.BytesIO()
        Image.new("RGB", (32, 32), "white").save(stream, format="PNG")
        content, mime = stream.getvalue(), "image/png"
    else:
        content = sorted((Path("data/image/dataset") / species).glob("*.jpg"))[0].read_bytes()
        mime = "image/jpeg"
    response = await client.post(
        f"/api/v1/conversations/{sid}/images", content=content, headers={"Content-Type": mime}
    )
    assert response.status_code == 201, response.text
    return response.json()["image_id"]


async def submit(client, runs, sid, payload, clarify=False):
    oid = uuid4()
    route = "clarifications" if clarify else "turns"
    response = await client.post(
        f"/api/v1/conversations/{sid}/{route}", json={"request_id": str(oid), **payload}
    )
    assert response.status_code == 202, response.text
    task = runs.tasks.get(oid)
    if task:
        await asyncio.wait_for(asyncio.shield(task), 60)
    value = (await client.get(f"/api/v1/runs/{oid}")).json()
    assert value["status"] == "complete", value
    return value["result"]


async def test_cnn_vector_confirmation_then_graph_followup(image_api):
    client, runs, sid = image_api
    assert (await client.get("/api/v1/capabilities")).json()["image_classifier"]
    iid = await upload(client, sid)
    result = await submit(client, runs, sid, {"image_id": iid})
    assert result["status"] == "WAITING_USER" and result["mode"] == "discovery"
    visual = result["image_understanding"]
    assert not visual["placeholder"] and visual["reference_ids"] and visual["evidence"]
    assert visual["candidates"][0]["label"].lower() == "azadirachta indica"
    candidate = visual["candidates"][0]["plant_id"]
    confirmed = await submit(
        client,
        runs,
        sid,
        {
            "clarification_id": result["clarification"]["clarification_id"],
            "selected_plant_id": candidate,
        },
        True,
    )
    assert confirmed["mode"] == "conversation"
    assert confirmed["correlation"]["run_id"] == result["correlation"]["run_id"]
    response = await submit(client, runs, sid, {"text": "What phytochemicals does it contain?"})
    assert response["active_plant"]["plant_id"] == candidate
    assert response["response"] is not None, {
        "status": response["status"],
        "clarification": response["clarification"],
        "understanding": response["understanding"],
    }
    assert response["response"]["citation_ids"]


async def test_clearer_image_resumes_same_checkpoint(image_api):
    client, runs, sid = image_api
    first = await submit(client, runs, sid, {"image_id": await upload(client, sid, bad=True)})
    assert not first["image_understanding"]["quality"]["usable"]
    second = await submit(
        client,
        runs,
        sid,
        {
            "clarification_id": first["clarification"]["clarification_id"],
            "image_id": await upload(client, sid),
        },
        True,
    )
    assert second["correlation"]["run_id"] == first["correlation"]["run_id"]
    assert second["image_understanding"]["quality"]["usable"]
    assert second["image_understanding"]["candidates"]
    assert second["status"] == "WAITING_USER"


async def test_text_image_disagreement_requires_clarification(image_api):
    client, runs, sid = image_api
    result = await submit(
        client,
        runs,
        sid,
        {"text": "neem", "image_id": await upload(client, sid, "Ocimum tenuiflorum")},
    )
    assert result["status"] == "WAITING_USER"
    state = await runs.service.load(UUID(sid))
    assert state.evidence.contradictions and state.evidence.image
    assert state.context.active_plant is None


async def test_text_image_agreement_answers_first_question_with_graph_evidence(image_api):
    client, runs, sid = image_api
    result = await submit(
        client,
        runs,
        sid,
        {
            "text": "What phytochemicals are in neem?",
            "image_id": await upload(client, sid),
        },
    )
    assert result["status"] == "COMPLETE", result
    assert result["mode"] == "conversation"
    assert result["active_plant"]["label"].lower() == "azadirachta indica"
    assert result["image_understanding"]["evidence"]
    assert result["response"]["citation_ids"]
    evidence = await client.get(f"/api/v1/runs/{result['correlation']['correlation_id']}/evidence")
    assert evidence.status_code == 200
    assert {"image", "graph"} <= {item["modality"] for item in evidence.json()["items"]}
