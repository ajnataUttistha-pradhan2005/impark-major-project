"""Opt-in tests create/delete only their own chats on local development stores."""

import asyncio
import io
import json
import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from PIL import Image

from backend.config.settings import Settings
from backend.database.postgres.client import StoreError
from backend.main import create_app

pytestmark = pytest.mark.skipif(os.getenv("CHAT_RUN_INTEGRATION") != "1", reason="Local opt-in")


@pytest_asyncio.fixture
async def api():
    config = Settings(
        llm_provider="grounded",
        text_semantic_enabled=False,
        enable_development_api=True,
        api_key=None,
    )
    assert config.application_env == "development"
    assert urlsplit(config.database_url.get_secret_value()).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(config.neo4j_uri).hostname in {"localhost", "127.0.0.1"}
    app = create_app(config)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ids = []

            async def create():
                response = await client.post("/api/v1/conversations", json={"title": "API test"})
                assert response.status_code == 201, response.text
                ids.append(response.json()["session_id"])
                return ids[-1]

            yield client, app.state.runs, create
            for sid in ids:
                rows = await app.state.postgres.read(
                    "SELECT operation_id FROM api_operation WHERE session_id=$1 "
                    "AND status IN ('accepted','running','interrupted')",
                    UUID(sid),
                )
                for row in rows:
                    await app.state.runs.cancel(row["operation_id"])
                if await app.state.postgres.scalar(
                    "SELECT count(*) FROM app_session WHERE session_id=$1", UUID(sid)
                ):
                    await app.state.runs.delete(UUID(sid))


async def finish(client, runs, sid, text="What phytochemicals are in neem?", **extra):
    oid = str(uuid4())
    response = await client.post(
        f"/api/v1/conversations/{sid}/turns", json={"request_id": oid, "text": text, **extra}
    )
    assert response.status_code == 202, response.text
    task = runs.tasks.get(UUID(oid))
    if task:
        await asyncio.wait_for(asyncio.shield(task), 60)
    result = (await client.get(f"/api/v1/runs/{oid}")).json()
    assert result["status"] == "complete", result
    return oid, result


async def test_session_lifecycle_history_stream_and_evidence(api):
    client, runs, create = api
    sid = await create()
    base = f"/api/v1/conversations/{sid}"
    state = (await client.get(base)).json()["state"]
    assert state["mode"] == "discovery" and "one plant" in state["session_notice"]
    oid, run = await finish(client, runs, sid)
    assert run["result"]["mode"] == "conversation"
    assert run["result"]["response"]["citation_ids"]
    response = await client.get(f"/api/v1/runs/{oid}/events")
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "run_completed"
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    types = [e["type"] for e in events]
    assert types.index("response_started") < types.index("response_delta")
    assert types.index("response_completed") < types.index("run_completed")
    answer = "".join(e["payload"]["text"] for e in events if e["type"] == "response_delta")
    assert answer == run["result"]["response"]["text"]
    replay = await client.get(f"/api/v1/runs/{oid}/events", headers={"Last-Event-ID": "2"})
    assert "id: 1\n" not in replay.text and "id: 3\n" in replay.text
    assert (
        await client.get(f"/api/v1/runs/{oid}/events", headers={"Last-Event-ID": "-1"})
    ).status_code == 422
    evidence = (await client.get(f"/api/v1/runs/{oid}/evidence")).json()["items"]
    assert set(run["result"]["response"]["citation_ids"]) <= {e["evidence_id"] for e in evidence}
    messages = (await client.get(base + "/messages")).json()["items"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == answer
    assert (await client.patch(base, json={"title": "Renamed", "archived": True})).json()[
        "archived"
    ]
    blocked = await client.post(base + "/turns", json={"request_id": str(uuid4()), "text": "hello"})
    assert blocked.status_code == 409
    await client.patch(base, json={"archived": False})
    assert any(
        s["session_id"] == sid for s in (await client.get("/api/v1/conversations")).json()["items"]
    )
    assert (await client.delete(base)).status_code == 204
    assert (await client.get(base)).status_code == 404
    assert (await client.get(f"/api/v1/runs/{oid}")).status_code == 404


async def test_idempotency_replay_conflict_and_single_plant(api):
    client, runs, create = api
    sid = await create()
    oid, first = await finish(client, runs, sid)
    original = {"request_id": oid, "text": "What phytochemicals are in neem?"}
    # Replays must work even when capacity is exhausted.
    runs.service.settings.max_active_runs = 1
    blocker = asyncio.create_task(asyncio.sleep(60))
    runs.tasks[uuid4()] = blocker
    try:
        replay = await client.post(f"/api/v1/conversations/{sid}/turns", json=original)
        assert replay.status_code == 202 and replay.json() == first
    finally:
        blocker.cancel()
        await asyncio.gather(blocker, return_exceptions=True)
        runs.tasks = {k: v for k, v in runs.tasks.items() if v is not blocker}
    conflict = await client.post(
        f"/api/v1/conversations/{sid}/turns", json={**original, "text": "different"}
    )
    assert conflict.status_code == 409
    _, other = await finish(client, runs, sid, "Tell me about tulsi")
    assert (
        other["result"]["active_plant"]["plant_id"] == first["result"]["active_plant"]["plant_id"]
    )
    assert "new chat" in other["result"]["response"]["text"].lower()
    assert len((await client.get(f"/api/v1/conversations/{sid}/messages")).json()["items"]) == 4


async def test_immediate_cancellation_and_active_run_conflict(api, monkeypatch):
    client, runs, create = api
    sid = await create()
    started = asyncio.Event()

    async def delayed(*args, **kwargs):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(runs.service, "submit", delayed)
    oid = str(uuid4())
    response = await client.post(
        f"/api/v1/conversations/{sid}/turns", json={"request_id": oid, "text": "neem"}
    )
    assert response.status_code == 202
    conflict = await client.post(
        f"/api/v1/conversations/{sid}/turns", json={"request_id": str(uuid4()), "text": "neem"}
    )
    assert conflict.status_code == 409
    assert (await client.delete(f"/api/v1/conversations/{sid}")).status_code == 409
    cancelled = await client.post(f"/api/v1/runs/{oid}/cancel")
    assert cancelled.json()["status"] == "cancelled", cancelled.text
    assert (await client.post(f"/api/v1/runs/{oid}/cancel")).json()["status"] == "cancelled"
    assert (await client.post(f"/api/v1/runs/{oid}/resume")).status_code == 409


async def test_durable_images_validation_and_session_scope(api):
    client, runs, create = api
    sid, other = await create(), await create()
    base = f"/api/v1/conversations/{sid}/images"
    assert (
        await client.post(base, content=b"fake", headers={"Content-Type": "image/png"})
    ).status_code == 422
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12)).save(buffer, format="PNG")
    uploaded = await client.post(
        base, content=buffer.getvalue(), headers={"Content-Type": "image/png"}
    )
    assert uploaded.status_code == 201
    iid = uploaded.json()["image_id"]
    assert (await client.get(base + "/" + iid)).content == buffer.getvalue()
    assert (await client.get(f"/api/v1/conversations/{other}/images/{iid}")).status_code == 404
    runs.service.images.clear()
    _, result = await finish(client, runs, sid, text="neem", image_id=iid)
    assert result["status"] == "complete"
    assert (await client.delete(base + "/" + iid)).status_code == 204


async def test_clarification_lineage_and_restart_before_reply(api):
    client, runs, create = api
    sid = await create()
    _, first = await finish(client, runs, sid, "unknown plant zzzq")
    pending = first["result"]["clarification"]
    assert pending
    oid = uuid4()
    from backend.api.schemas.chat import ChatRequest
    from backend.contracts.response import ClarificationResponse

    # Accept without scheduling to simulate shutdown before execution begins.
    launch = runs._launch
    runs._launch = lambda *args: None
    try:
        await runs.start(
            UUID(sid),
            oid,
            ChatRequest(text="neem"),
            ClarificationResponse(clarification_id=pending["clarification_id"], text="neem"),
        )
    finally:
        runs._launch = launch
    await runs.store.interrupt_stale()
    await runs.resume(oid)
    await asyncio.wait_for(runs.tasks[oid], 60)
    result = (await client.get(f"/api/v1/runs/{oid}")).json()
    assert result["status"] == "complete", result
    assert result["result"]["correlation"]["run_id"] == first["result"]["correlation"]["run_id"]
    assert result["result"]["mode"] == "conversation"


async def test_task_cancelled_before_first_instruction_is_finalized(api):
    client, runs, create = api
    from backend.api.schemas.chat import ChatRequest

    sid, oid = await create(), uuid4()
    await runs.start(UUID(sid), oid, ChatRequest(text="neem"))
    runs.tasks[oid].cancel()  # No yield: coroutine has not entered its try/finally yet.
    result = await runs.cancel(oid)
    assert result.status == "cancelled"
    messages = (await client.get(f"/api/v1/conversations/{sid}/messages")).json()["items"]
    assert messages[-1]["status"] == "cancelled"


async def test_event_writer_failure_finalizes_run_instead_of_leaving_it_running(api, monkeypatch):
    client, runs, create = api
    sid = await create()
    original_event = runs.store.event
    failed_once = False

    async def fail_once(oid, kind, payload):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise StoreError("QUERY")
        return await original_event(oid, kind, payload)

    monkeypatch.setattr(runs.store, "event", fail_once)
    oid = uuid4()
    accepted = await client.post(
        f"/api/v1/conversations/{sid}/turns",
        json={"request_id": str(oid), "text": "What phytochemicals are in neem?"},
    )
    assert accepted.status_code == 202
    await asyncio.wait_for(runs.tasks[oid], 60)
    result = (await client.get(f"/api/v1/runs/{oid}")).json()
    assert result["status"] == "failed" and result["error_code"] == "RUN_FAILED"
    assert "run_failed" in (await client.get(f"/api/v1/runs/{oid}/events")).text


@pytest.mark.parametrize("reply", [True, False])
async def test_restart_after_reply_completed_does_not_apply_it_again(api, monkeypatch, reply):
    client, runs, create = api
    sid = await create()
    if reply:
        await finish(client, runs, sid, "unknown plant zzzq")
    original_status = runs.store.status
    interrupted = False

    async def crash_after_execution(oid, status, *args, **kwargs):
        nonlocal interrupted
        if status == "complete" and not interrupted:
            interrupted = True
            raise asyncio.CancelledError()
        return await original_status(oid, status, *args, **kwargs)

    monkeypatch.setattr(runs.store, "status", crash_after_execution)
    oid = uuid4()
    response = await client.post(
        f"/api/v1/conversations/{sid}/turns",
        json={"request_id": str(oid), "text": "neem" if reply else "unknown plant zzzq"},
    )
    assert response.status_code == 202
    await runs.tasks[oid]
    before = await runs.service.load(UUID(sid))
    assert (await runs.store.operation(oid))["status"] == "interrupted"
    await runs.resume(oid)
    await runs.tasks[oid]
    after = await runs.service.load(UUID(sid))
    assert before.correlation.run_id == after.correlation.run_id
    assert len(before.execution.observations) == len(after.execution.observations)
    assert before.clarification_count == after.clarification_count
    assert before.clarification == after.clarification
    assert (await runs.store.operation(oid))["status"] == "complete"
