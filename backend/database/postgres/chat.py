"""Durable single-workspace chat storage. Mutations are explicit transactions."""

import json
from typing import Any
from uuid import UUID, uuid4

from backend.api.schemas.chat import ChatResponse
from backend.api.schemas.platform import (
    MessagePage,
    MessageView,
    RunView,
    SessionPage,
    SessionSummary,
    StreamEvent,
)
from backend.database.postgres.client import PostgresClient
from backend.services.conversations import public_state
from backend.services.errors import ServiceError
from backend.state.models import ConversationState


def decode(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def run_view(row: dict[str, Any]) -> RunView:
    return RunView(
        operation_id=row["operation_id"],
        session_id=row["session_id"],
        status=row["status"],
        result=decode(row.get("result")),
        error_code=row.get("error_code"),
        events_url=f"/api/v1/runs/{row['operation_id']}/events",
    )


class ChatStore:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    async def session(self, sid: UUID) -> SessionSummary:
        row = await self.client.single("SELECT * FROM app_session WHERE session_id=$1", sid)
        if row is None:
            raise ServiceError("NOT_FOUND", "Conversation not found", 404)
        return self._session(row)

    @staticmethod
    def _session(row: dict[str, Any]) -> SessionSummary:
        state = ConversationState.model_validate_json(row["state"])
        return SessionSummary(
            session_id=row["session_id"],
            title=row["title"],
            archived=row["archived"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            state=public_state(state),
        )

    async def sessions(self, archived: bool, limit: int, offset: int) -> SessionPage:
        rows = await self.client.read(
            "SELECT * FROM app_session WHERE archived=$1 "
            "ORDER BY updated_at DESC,session_id LIMIT $2 OFFSET $3",
            archived,
            limit + 1,
            offset,
        )
        return SessionPage(
            items=[self._session(row) for row in rows[:limit]],
            next_offset=offset + limit if len(rows) > limit else None,
        )

    async def update(self, sid: UUID, title: str | None, archived: bool | None) -> SessionSummary:
        await self.client.write(
            "UPDATE app_session SET title=coalesce($2,title), archived=coalesce($3,archived), "
            "updated_at=now() WHERE session_id=$1",
            sid,
            title,
            archived,
        )
        return await self.session(sid)

    async def messages(self, sid: UUID, limit: int, offset: int) -> MessagePage:
        await self.session(sid)
        rows = await self.client.read(
            "SELECT * FROM chat_message WHERE session_id=$1 ORDER BY created_at,"
            "CASE role WHEN 'user' THEN 0 ELSE 1 END,message_id "
            "LIMIT $2 OFFSET $3",
            sid,
            limit + 1,
            offset,
        )
        return MessagePage(
            items=[
                MessageView(
                    message_id=r["message_id"],
                    operation_id=r["operation_id"],
                    role=r["role"],
                    content=r["content"],
                    status=r["status"],
                    data=decode(r["data"]),
                    created_at=r["created_at"],
                )
                for r in rows[:limit]
            ],
            next_offset=offset + limit if len(rows) > limit else None,
        )

    async def operation(self, oid: UUID) -> dict[str, Any]:
        row = await self.client.single("SELECT * FROM api_operation WHERE operation_id=$1", oid)
        if row is None:
            raise ServiceError("NOT_FOUND", "Run not found", 404)
        return row

    async def accept(
        self,
        oid: UUID,
        sid: UUID,
        digest: str,
        payload: dict[str, Any],
        text: str,
        *,
        capacity: bool = True,
        run_id: UUID | None = None,
    ) -> tuple[RunView, bool]:
        async with self.client.transaction(write=True) as tx:
            session = await tx.fetchrow(
                "SELECT archived FROM app_session WHERE session_id=$1 FOR UPDATE", sid
            )
            if session is None:
                raise ServiceError("NOT_FOUND", "Conversation not found", 404)
            old = await tx.fetchrow("SELECT * FROM api_operation WHERE operation_id=$1", oid)
            if old:
                if old["session_id"] != sid or old["request_hash"] != digest:
                    raise ServiceError(
                        "IDEMPOTENCY_CONFLICT", "Request ID already used for different input", 409
                    )
                return run_view(dict(old)), False
            if not capacity:
                raise ServiceError("BUSY", "Backend capacity reached; retry shortly", 429)
            if session["archived"]:
                raise ServiceError("ARCHIVED", "Restore the chat before sending messages", 409)
            active = await tx.fetchval(
                "SELECT 1 FROM api_operation WHERE session_id=$1 "
                "AND status IN ('accepted','running','interrupted')",
                sid,
            )
            if active:
                raise ServiceError("CONFLICT", "Conversation has an active or interrupted run", 409)
            row = await tx.fetchrow(
                "INSERT INTO api_operation"
                "(operation_id,session_id,request_hash,request,status,run_id) "
                "VALUES($1,$2,$3,$4::jsonb,'accepted',$5) RETURNING *",
                oid,
                sid,
                digest,
                json.dumps(payload),
                run_id,
            )
            for role, content, status in [("user", text, "complete"), ("assistant", "", "pending")]:
                await tx.execute(
                    "INSERT INTO chat_message "
                    "(message_id,session_id,operation_id,role,content,status,data) "
                    "VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)",
                    uuid4(),
                    sid,
                    oid,
                    role,
                    content,
                    status,
                    json.dumps(payload if role == "user" else {}),
                )
            await tx.execute("UPDATE app_session SET updated_at=now() WHERE session_id=$1", sid)
            return run_view(dict(row)), True

    async def status(
        self,
        oid: UUID,
        status: str,
        result: ChatResponse | None = None,
        error: str | None = None,
        *,
        evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        async with self.client.transaction(write=True) as tx:
            await tx.fetchval(
                "SELECT operation_id FROM api_operation WHERE operation_id=$1 FOR UPDATE", oid
            )
            if status == "complete" and result is not None:
                sequence = await tx.fetchval(
                    "SELECT coalesce(max(sequence),0)+1 FROM api_event WHERE operation_id=$1", oid
                )
                event = StreamEvent(
                    operation_id=oid,
                    sequence=sequence,
                    type="run_completed",
                    payload=result.model_dump(mode="json"),
                )
                await tx.execute(
                    "INSERT INTO api_event(operation_id,sequence,event) VALUES($1,$2,$3::jsonb)",
                    oid,
                    sequence,
                    event.model_dump_json(),
                )
            await tx.execute(
                "UPDATE api_operation SET status=$2,result=$3::jsonb,"
                "error_code=$4,updated_at=now() "
                "WHERE operation_id=$1",
                oid,
                status,
                result.model_dump_json() if result else None,
                error,
            )
            if status in {"complete", "failed", "cancelled", "interrupted"}:
                content = (
                    result.response.text
                    if result and result.response
                    else result.clarification.question
                    if result and result.clarification
                    else None
                )
                await tx.execute(
                    "UPDATE chat_message SET status=$2,content=coalesce($3,content),data=$4::jsonb "
                    "WHERE operation_id=$1 AND role='assistant'",
                    oid,
                    status,
                    content,
                    json.dumps(
                        {
                            "result": result.model_dump(mode="json") if result else None,
                            "evidence": evidence or [],
                        }
                    ),
                )

    async def event(self, oid: UUID, kind: str, payload: dict[str, Any]) -> StreamEvent:
        async with self.client.transaction(write=True) as tx:
            await tx.fetchval(
                "SELECT operation_id FROM api_operation WHERE operation_id=$1 FOR UPDATE", oid
            )
            sequence = await tx.fetchval(
                "SELECT coalesce(max(sequence),0)+1 FROM api_event WHERE operation_id=$1", oid
            )
            event = StreamEvent.model_validate(
                dict(operation_id=oid, sequence=sequence, type=kind, payload=payload)
            )
            await tx.execute(
                "INSERT INTO api_event(operation_id,sequence,event) VALUES($1,$2,$3::jsonb)",
                oid,
                sequence,
                event.model_dump_json(),
            )
            if kind == "progress" and payload.get("run_id"):
                await tx.execute(
                    "UPDATE api_operation SET run_id=coalesce(run_id,$2) WHERE operation_id=$1",
                    oid,
                    UUID(str(payload["run_id"])),
                )
            if kind == "response_delta":
                await tx.execute(
                    "UPDATE chat_message SET content=content || $2,status='streaming' "
                    "WHERE operation_id=$1 AND role='assistant'",
                    oid,
                    payload.get("text", ""),
                )
            elif kind == "response_reset":
                await tx.execute(
                    "UPDATE chat_message SET content='',status='pending' "
                    "WHERE operation_id=$1 AND role='assistant'",
                    oid,
                )
            return event

    async def events(self, oid: UUID, after: int) -> list[StreamEvent]:
        rows = await self.client.read(
            "SELECT event FROM api_event WHERE operation_id=$1 AND sequence>$2 "
            "ORDER BY sequence LIMIT 100",
            oid,
            after,
        )
        return [StreamEvent.model_validate_json(r["event"]) for r in rows]

    async def interrupt_stale(self) -> None:
        rows = await self.client.read(
            "SELECT operation_id FROM api_operation WHERE status IN ('accepted','running')"
        )
        for row in rows:
            await self.event(row["operation_id"], "run_interrupted", {"reason": "backend_restart"})
            await self.status(row["operation_id"], "interrupted")

    async def delete(self, sid: UUID) -> list[UUID]:
        async with self.client.transaction(write=True) as tx:
            await tx.fetchval(
                "SELECT session_id FROM app_session WHERE session_id=$1 FOR UPDATE", sid
            )
            active = await tx.fetchval(
                "SELECT 1 FROM api_operation WHERE session_id=$1 "
                "AND status IN ('accepted','running','interrupted')",
                sid,
            )
            if active:
                raise ServiceError("CONFLICT", "Cancel the active run before deleting", 409)
            rows = await tx.fetch("SELECT run_id FROM app_turn WHERE session_id=$1", sid)
            await tx.execute("DELETE FROM domain_trace WHERE session_id=$1", sid)
            await tx.execute("DELETE FROM app_turn WHERE session_id=$1", sid)
            await tx.execute("DELETE FROM app_session WHERE session_id=$1", sid)
            return [r["run_id"] for r in rows]
