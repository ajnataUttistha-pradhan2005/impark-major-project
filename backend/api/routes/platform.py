"""Versioned, single-workspace API. Routes translate transport, never choose agents."""

import asyncio
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPBearer

from backend.api.schemas.chat import AutocompleteResponse, ChatRequest
from backend.api.schemas.platform import (
    ClarificationCreate,
    EvidencePage,
    MessagePage,
    RunView,
    SessionCreate,
    SessionPage,
    SessionPatch,
    SessionSummary,
    TurnCreate,
)
from backend.contracts.agents import ImageReference
from backend.contracts.response import ClarificationResponse
from backend.database.postgres.chat import run_view
from backend.services.chat_images import ChatImages
from backend.services.errors import ServiceError
from backend.services.runs import RunManager


async def authorize(request: Request) -> None:
    import secrets

    settings = request.app.state.settings
    if settings.api_key:
        expected = "Bearer " + settings.api_key.get_secret_value()
        if not secrets.compare_digest(
            request.headers.get("authorization", "").encode(), expected.encode()
        ):
            raise ServiceError("UNAUTHORIZED", "Valid bearer token required", 401)
    elif not (settings.application_env == "development" and settings.enable_development_api):
        raise ServiceError("FORBIDDEN", "API authentication is not configured", 403)


def manager(request: Request) -> RunManager:
    value: RunManager | None = request.app.state.runs
    if value is None:
        raise ServiceError("UNAVAILABLE", "Persistent chat storage is not configured", 503)
    return value


router = APIRouter(
    prefix="/api/v1",
    dependencies=[
        Depends(authorize),
        Depends(HTTPBearer(auto_error=False, description="Shared demo workspace API key")),
    ],
)
Manager = Annotated[RunManager, Depends(manager)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, Any]:
    return {
        "api_version": "1",
        "workspace": "single-user",
        "streaming": "sse",
        "one_plant_per_session": True,
        "image_upload": True,
        "image_classifier": request.app.state.image_provider is not None,
        "image_scope": "40 leaf classes; confirmation required",
        "image_part_classifier": False,
        "max_image_bytes": request.app.state.settings.max_image_bytes,
        "llm_provider": request.app.state.settings.agent_main_model_provider,
        "llm_model": (
            request.app.state.settings.agent_main_model
            or request.app.state.settings.llm_model
        ),
        "response_policy": "agentic-grounded-facts-and-labeled-general-context",
        "public_trace": False,
    }


@router.post("/conversations", response_model=SessionSummary, status_code=201)
async def create(body: SessionCreate, request: Request, runs: Manager) -> SessionSummary:
    state = await runs.service.create(request.state.correlation_id)
    return await runs.store.update(state.correlation.session_id, body.title, False)


@router.get("/conversations", response_model=SessionPage)
async def sessions(
    runs: Manager, archived: bool = False, limit: Limit = 30, offset: Offset = 0
) -> SessionPage:
    return await runs.store.sessions(archived, limit, offset)


@router.get("/conversations/{sid}", response_model=SessionSummary)
async def session(sid: UUID, runs: Manager) -> SessionSummary:
    return await runs.store.session(sid)


@router.patch("/conversations/{sid}", response_model=SessionSummary)
async def update(sid: UUID, body: SessionPatch, runs: Manager) -> SessionSummary:
    return await runs.store.update(sid, body.title, body.archived)


@router.delete("/conversations/{sid}", status_code=204)
async def delete(sid: UUID, runs: Manager) -> Response:
    await runs.delete(sid)
    return Response(status_code=204)


@router.get("/conversations/{sid}/messages", response_model=MessagePage)
async def messages(sid: UUID, runs: Manager, limit: Limit = 50, offset: Offset = 0) -> MessagePage:
    return await runs.store.messages(sid, limit, offset)


@router.post("/conversations/{sid}/turns", response_model=RunView, status_code=202)
async def turn(sid: UUID, body: TurnCreate, runs: Manager) -> RunView:
    return await runs.start(
        sid, body.request_id, ChatRequest.model_validate(body.model_dump(exclude={"request_id"}))
    )


@router.post("/conversations/{sid}/clarifications", response_model=RunView, status_code=202)
async def clarification(sid: UUID, body: ClarificationCreate, runs: Manager) -> RunView:
    reply = ClarificationResponse.model_validate(body.model_dump(exclude={"request_id"}))
    return await runs.start(
        sid, body.request_id, ChatRequest(text=reply.text, image_id=reply.image_id), reply
    )


@router.get("/discovery/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    runs: Manager, q: Annotated[str, Query(min_length=1, max_length=200)]
) -> AutocompleteResponse:
    return await runs.service.autocomplete(q)


@router.get("/runs/{oid}", response_model=RunView)
async def run(oid: UUID, runs: Manager) -> RunView:
    return run_view(await runs.store.operation(oid))


@router.post("/runs/{oid}/cancel", response_model=RunView)
async def cancel(oid: UUID, runs: Manager) -> RunView:
    return await runs.cancel(oid)


@router.post("/runs/{oid}/resume", response_model=RunView, status_code=202)
async def resume(oid: UUID, runs: Manager) -> RunView:
    return await runs.resume(oid)


@router.get("/runs/{oid}/evidence", response_model=EvidencePage)
async def evidence(oid: UUID, runs: Manager) -> EvidencePage:
    operation = await runs.store.operation(oid)
    from backend.database.postgres.chat import decode

    snapshot = await runs.store.client.single(
        "SELECT data FROM chat_message WHERE operation_id=$1 AND role='assistant'",
        oid,
    )
    data = decode(snapshot["data"]) if snapshot else {}
    items = data.get("evidence", [])
    result = data.get("result") or {}
    response = result.get("response") or {}
    cited = set(response.get("citation_ids") or [])
    present = {item.get("evidence_id") for item in items}
    missing = cited - present
    if missing:
        # A response may cite evidence retained from an earlier turn. Resolve
        # those citations only inside this session, never from another chat.
        rows = await runs.store.client.read(
            "SELECT e.value AS item FROM chat_message m "
            "CROSS JOIN LATERAL jsonb_array_elements(coalesce(m.data->'evidence','[]'::jsonb)) "
            "AS e(value) WHERE m.session_id=$1 AND m.role='assistant' "
            "AND e.value->>'evidence_id'=ANY($2::text[]) "
            "ORDER BY m.created_at DESC LIMIT 100",
            operation["session_id"],
            list(missing),
        )
        for row in rows:
            item = decode(row["item"])
            if item.get("evidence_id") in missing:
                items.append(item)
                missing.discard(item["evidence_id"])
    return EvidencePage(items=items)


@router.get("/runs/{oid}/events", response_class=StreamingResponse)
async def events(
    oid: UUID,
    request: Request,
    runs: Manager,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    await runs.store.operation(oid)
    try:
        header_cursor = int(last_event_id) if last_event_id is not None else 0
        if header_cursor < 0:
            raise ValueError
        cursor = max(after, header_cursor)
    except ValueError:
        raise ServiceError("INVALID_CURSOR", "Invalid event cursor", 422) from None
    latest = await runs.store.client.scalar(
        "SELECT coalesce(max(sequence),0) FROM api_event WHERE operation_id=$1", oid
    )
    if cursor > latest:
        raise ServiceError("INVALID_CURSOR", "Event cursor is ahead of this run", 422)

    async def stream() -> Any:
        nonlocal cursor
        heartbeat = time.monotonic()
        while not await request.is_disconnected():
            batch = await runs.store.events(oid, cursor)
            for event in batch:
                cursor = event.sequence
                yield f"id: {cursor}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
            if batch:
                continue
            status = (await runs.store.operation(oid))["status"]
            if status in {"complete", "failed", "cancelled", "interrupted"}:
                # Completion may commit between the batch read and status read.
                # Re-read after observing terminal status so its final event cannot be lost.
                tail = await runs.store.events(oid, cursor)
                for event in tail:
                    cursor = event.sequence
                    yield f"id: {cursor}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
                if not tail:
                    break
                continue
            if time.monotonic() - heartbeat >= 10:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/conversations/{sid}/images", response_model=ImageReference, status_code=201)
async def upload(sid: UUID, request: Request, runs: Manager) -> ImageReference:
    await runs.store.session(sid)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > runs.service.settings.max_image_bytes:
            raise ServiceError("IMAGE_TOO_LARGE", "Image exceeds upload limit", 413)
        data.extend(chunk)
    return await ChatImages(runs.store, runs.service.settings).upload(
        sid, bytes(data), request.headers.get("content-type", "")
    )


@router.get("/conversations/{sid}/images/{iid}")
async def image(sid: UUID, iid: UUID, runs: Manager) -> Response:
    row = await runs.store.client.single(
        "SELECT metadata,content FROM chat_image WHERE session_id=$1 AND image_id=$2", sid, iid
    )
    if row is None:
        raise ServiceError("NOT_FOUND", "Image not found", 404)
    metadata = ImageReference.model_validate_json(row["metadata"]).metadata
    return Response(
        row["content"],
        media_type=metadata.mime_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/conversations/{sid}/images", response_model=list[ImageReference])
async def images(sid: UUID, runs: Manager) -> list[ImageReference]:
    await runs.store.session(sid)
    rows = await runs.store.client.read(
        "SELECT metadata FROM chat_image WHERE session_id=$1 ORDER BY created_at,image_id", sid
    )
    return [ImageReference.model_validate_json(row["metadata"]) for row in rows]


@router.delete("/conversations/{sid}/images/{iid}", status_code=204)
async def delete_image(sid: UUID, iid: UUID, runs: Manager) -> Response:
    async with runs.store.client.transaction(write=True) as tx:
        await tx.fetchval("SELECT session_id FROM app_session WHERE session_id=$1 FOR UPDATE", sid)
        busy = await tx.fetchval(
            "SELECT 1 FROM api_operation WHERE session_id=$1 "
            "AND status IN ('accepted','running','interrupted')",
            sid,
        )
        if busy:
            raise ServiceError("CONFLICT", "Cannot remove images during an active run", 409)
        await tx.execute("DELETE FROM chat_image WHERE session_id=$1 AND image_id=$2", sid, iid)
    runs.service.images.get(sid, {}).pop(iid, None)
    return Response(status_code=204)
