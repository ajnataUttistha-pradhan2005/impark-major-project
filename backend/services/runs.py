"""Durable run wrapper around the existing harness, not another decision engine."""

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from typing import Any
from uuid import UUID

from backend.api.schemas.chat import ChatRequest
from backend.api.schemas.platform import RunView
from backend.contracts.agents import ImageReference
from backend.contracts.response import ClarificationResponse
from backend.database.postgres.chat import ChatStore, decode, run_view
from backend.database.postgres.client import StoreError
from backend.services.conversations import ConversationService, public_state
from backend.services.errors import ServiceError
from backend.services.live import publisher
from backend.state.models import ConversationState, TaskStatus


class RunManager:
    def __init__(self, service: ConversationService, store: ChatStore) -> None:
        self.service, self.store = service, store
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.cancelled: set[UUID] = set()
        self.closing = False
        self.gate = asyncio.Lock()

    async def start(
        self,
        sid: UUID,
        oid: UUID,
        request: ChatRequest,
        clarification: ClarificationResponse | None = None,
    ) -> RunView:
        payload = {
            "request": request.model_dump(mode="json"),
            "clarification": clarification.model_dump(mode="json") if clarification else None,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        async with self.gate:
            state = await self.service.load(sid)
            if state.termination.status == TaskStatus.WAITING_USER and clarification is None:
                assert state.clarification is not None
                payload["clarification"] = ClarificationResponse(
                    clarification_id=state.clarification.clarification_id,
                    text=request.text or "Selected candidate",
                    image_id=request.image_id,
                    selected_plant_id=str(request.selected_plant_id)
                    if request.selected_plant_id
                    else None,
                ).model_dump(mode="json")
            view, created = await self.store.accept(
                oid,
                sid,
                digest,
                payload,
                request.text or "[image/selection]",
                capacity=not self.closing
                and len(self.tasks) < self.service.settings.max_active_runs,
                run_id=state.correlation.run_id
                if state.termination.status == TaskStatus.WAITING_USER
                else None,
            )
            if created:
                self._launch(oid)
            return view

    def _launch(self, oid: UUID, resume: bool = False) -> None:
        task = asyncio.create_task(self._run(oid, resume), name=f"chat-run-{oid}")
        self.tasks[oid] = task

        def finished(value: asyncio.Task[None]) -> None:
            self.tasks.pop(oid, None)
            if not value.cancelled() and value.exception() is not None:
                logging.getLogger(__name__).error(
                    "run_persistence_failed", extra={"operation_id": str(oid)}
                )

        task.add_done_callback(finished)

    async def _run(self, oid: UUID, resume: bool) -> None:
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue(maxsize=2048)

        async def persist() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    await self.store.event(oid, *item)
                finally:
                    queue.task_done()

        def emit(kind: str, payload: dict[str, Any]) -> None:
            if writer.done():
                writer.result()
            queue.put_nowait((kind, payload))

        writer = asyncio.create_task(persist())
        token = publisher.set(emit)
        sid: UUID | None = None
        try:
            row = await self.store.operation(oid)
            sid = row["session_id"]
            payload = decode(row["request"])
            request = ChatRequest.model_validate(payload["request"])
            clarification = (
                ClarificationResponse.model_validate(payload["clarification"])
                if payload["clarification"]
                else None
            )
            await self.store.status(oid, "running")
            emit("run_started", {"session_id": str(sid), "resumed": resume})
            if resume:
                emit("response_reset", {"reason": "resuming_interrupted_generation"})
            if request.image_id:
                image = await self.store.client.single(
                    "SELECT metadata FROM chat_image WHERE session_id=$1 AND image_id=$2",
                    sid,
                    request.image_id,
                )
                if image is None:
                    raise ServiceError("INVALID_INPUT", "Unknown image for this conversation", 422)
                self.service.images.setdefault(sid, {})[request.image_id] = (
                    ImageReference.model_validate_json(image["metadata"])
                )
            state = await self.service.load(sid)
            same_run = state.correlation.correlation_id == oid or (
                row.get("run_id") == state.correlation.run_id
            )
            pending_reply = (
                state.termination.status == TaskStatus.WAITING_USER
                and state.clarification is not None
                and clarification is not None
                and clarification.clarification_id == state.clarification.clarification_id
            )
            if resume and same_run and not pending_reply:
                if state.termination.status == TaskStatus.RUNNING:
                    result = await self.service.recover(sid)
                else:
                    result = public_state(state)
            else:
                result = await self.service.submit(sid, request, oid, clarification)
            if result.clarification:
                emit("clarification_requested", result.clarification.model_dump(mode="json"))
            await self._drain(queue, writer)
            snapshot = await self.service.load(sid)
            await self.store.status(
                oid,
                "complete",
                result,
                evidence=[e.model_dump(mode="json") for e in snapshot.evidence.all_evidence()],
            )
        except asyncio.CancelledError:
            await self._drain_after_failure(queue, writer)
            explicit = oid in self.cancelled
            if explicit and sid:
                await self._cancel_state(sid, oid)
            status = "cancelled" if explicit else "interrupted"
            await self.store.event(
                oid,
                f"run_{status}",
                {"reason": "user_cancelled" if explicit else "backend_shutdown"},
            )
            await self.store.status(oid, status)
        except Exception as error:
            # Final job boundary: never publish exception messages, submitted secrets or SQL.
            code = error.code if isinstance(error, ServiceError) else "RUN_FAILED"
            await self._drain_after_failure(queue, writer)
            with suppress(StoreError):
                await self.store.event(
                    oid, "run_failed", {"code": code, "message": "Run could not be completed"}
                )
                await self.store.status(oid, "failed", error=code)
            if sid:
                await self._cancel_state(sid, oid, failed=True)
        finally:
            publisher.reset(token)
            self.cancelled.discard(oid)
            if not writer.done():
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    writer.cancel()
            try:
                await writer
            except asyncio.CancelledError:
                pass
            except Exception:
                # The operation status was finalized above if persistence is still available.
                logging.getLogger(__name__).warning("run_event_writer_failed")

    @classmethod
    async def _drain_after_failure(
        cls, queue: asyncio.Queue[tuple[str, dict[str, Any]] | None], writer: asyncio.Task[None]
    ) -> None:
        try:
            await cls._drain(queue, writer)
        except Exception:
            # A failed writer cannot consume the queue. Continue to direct final status writes.
            logging.getLogger(__name__).warning("run_event_writer_failed")

    @staticmethod
    async def _drain(
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None], writer: asyncio.Task[None]
    ) -> None:
        joined = asyncio.create_task(queue.join())
        try:
            done, _ = await asyncio.wait({joined, writer}, return_when=asyncio.FIRST_COMPLETED)
            if writer in done:
                writer.result()
            await joined
        finally:
            if not joined.done():
                joined.cancel()

    async def _cancel_state(self, sid: UUID, oid: UUID, failed: bool = False) -> None:
        state = await self.service.load(sid)
        row = await self.store.operation(oid)
        owned = state.correlation.correlation_id == oid or (
            row.get("run_id") == state.correlation.run_id
        )
        if state.termination.status != TaskStatus.RUNNING or not owned:
            return
        # Clarification shares the original correlation lineage; preserve its identity and budget.
        checkpoint = await self.service.graph.aget_state(self.service._config(state))
        if checkpoint.values:
            value = checkpoint.values["domain"]
            state = (
                value
                if isinstance(value, ConversationState)
                else ConversationState.model_validate(value)
            )
        state.termination.status = TaskStatus.FAILED if failed else TaskStatus.CANCELLED
        state.termination.reason = "Run failed" if failed else "Cancelled by user"
        state.response = None
        state.response_context = None
        await self.service.repository.save(state)

    async def cancel(self, oid: UUID) -> RunView:
        async with self.gate:
            return await self._cancel(oid)

    async def _cancel(self, oid: UUID) -> RunView:
        row = await self.store.operation(oid)
        if row["status"] in {"complete", "failed", "cancelled"}:
            return run_view(row)
        task = self.tasks.get(oid)
        if task:
            self.cancelled.add(oid)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        row = await self.store.operation(oid)
        if row["status"] not in {"complete", "failed", "cancelled"}:
            await self._cancel_state(row["session_id"], oid)
            await self.store.event(oid, "run_cancelled", {"reason": "user_cancelled"})
            await self.store.status(oid, "cancelled")
        self.cancelled.discard(oid)
        return run_view(await self.store.operation(oid))

    async def resume(self, oid: UUID) -> RunView:
        async with self.gate:
            row = await self.store.operation(oid)
            if row["status"] != "interrupted" or oid in self.tasks:
                raise ServiceError("CONFLICT", "Run is not interrupted", 409)
            if self.closing or len(self.tasks) >= self.service.settings.max_active_runs:
                raise ServiceError("BUSY", "Backend capacity reached", 429)
            await self.store.status(oid, "accepted")
            self._launch(oid, True)
            return run_view(await self.store.operation(oid))

    async def close(self) -> None:
        self.closing = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.store.interrupt_stale()

    async def delete(self, sid: UUID) -> None:
        async with self.gate:
            await self.store.session(sid)
            active = await self.store.client.scalar(
                "SELECT count(*) FROM api_operation WHERE session_id=$1 "
                "AND status IN ('accepted','running','interrupted')",
                sid,
            )
            if active:
                raise ServiceError("CONFLICT", "Cancel the active run before deleting", 409)
            rows = await self.store.client.read(
                "SELECT run_id FROM app_turn WHERE session_id=$1",
                sid,
            )
            checkpointer = self.service.graph.checkpointer
            if checkpointer and not isinstance(checkpointer, bool):
                for row in rows:
                    await checkpointer.adelete_thread(str(row["run_id"]))
            await self.store.delete(sid)
            self.service.images.pop(sid, None)
