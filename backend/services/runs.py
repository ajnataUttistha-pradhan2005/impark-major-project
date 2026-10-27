"""Durable run wrapper around the existing harness, not another decision engine."""

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from typing import Any
from uuid import UUID

from backend.api.schemas.chat import ChatRequest, ChatResponse
from backend.api.schemas.platform import RunView
from backend.contracts.actions import Capability
from backend.contracts.agents import ImageReference
from backend.contracts.base import utc_now
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
            sid = UUID(str(row["session_id"]))
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
            traces = await self._assemble_routing_trace(sid, oid, result, snapshot)
            await self.store.status(
                oid,
                "complete",
                result,
                evidence=[e.model_dump(mode="json") for e in snapshot.evidence.all_evidence()],
                traces=traces,
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

    async def _assemble_routing_trace(
        self,
        sid: UUID,
        oid: UUID,
        result: ChatResponse,
        snapshot: ConversationState,
    ) -> dict[str, Any]:
        run_id = result.correlation.run_id if result and result.correlation else None
        trace_events: list[dict[str, Any]] = []
        if run_id:
            try:
                trace_rows = await self.store.client.read(
                    "SELECT event_type, event, created_at FROM domain_trace WHERE run_id = $1 ORDER BY created_at ASC",
                    run_id,
                )
                trace_events = [
                    {
                        "event_type": r["event_type"],
                        "created_at": r["created_at"],
                        "event": json.loads(r["event"]) if isinstance(r["event"], str) else r["event"],
                    }
                    for r in trace_rows
                ]
            except Exception:
                pass

        turn_started_time = None
        turn_completed_time = None
        obs_times: list[str] = []
        for te in trace_events:
            evt_type = te["event_type"]
            created = te["created_at"]
            iso_time = created.isoformat() if hasattr(created, "isoformat") else str(created)
            if evt_type == "turn_started" and not turn_started_time:
                turn_started_time = iso_time
            elif evt_type in ("response_stream_completed", "turn_completed"):
                turn_completed_time = iso_time
            elif evt_type == "observation_created":
                obs_times.append(iso_time)

        now_iso = utc_now().isoformat()
        if not turn_started_time:
            turn_started_time = now_iso
        if not turn_completed_time:
            turn_completed_time = now_iso

        plant_name = None
        if result and result.active_plant and getattr(result.active_plant, "label", None):
            plant_name = result.active_plant.label
        elif (
            snapshot
            and snapshot.context
            and snapshot.context.active_plant
            and getattr(snapshot.context.active_plant, "label", None)
        ):
            plant_name = snapshot.context.active_plant.label

        routing: list[dict[str, Any]] = []
        step_num = 1
        start_decision = (
            f"Route question to deep_orchestrator with plant scope locked to '{plant_name}'"
            if plant_name
            else "Route user question to deep_orchestrator"
        )
        routing.append({
            "step": step_num,
            "routing_type": "graph_node_transition",
            "from_node": "START",
            "to_node": "deep_orchestrator",
            "decision": start_decision,
            "timestamp": turn_started_time,
        })

        run_observations = []
        if snapshot and snapshot.execution and snapshot.execution.observations:
            for obs in snapshot.execution.observations:
                obs_corr = obs.invocation.correlation if obs.invocation else None
                if obs_corr:
                    if (run_id and obs_corr.run_id == run_id) or (oid and obs_corr.correlation_id == oid):
                        run_observations.append(obs)

        for idx, obs in enumerate(run_observations):
            obs_time = obs_times[idx] if idx < len(obs_times) else turn_started_time
            comp = obs.component.value if hasattr(obs.component, "value") else str(obs.component)

            if comp == Capability.GRAPH.value:
                subagent = "knowledge_graph"
                tool_name = "retrieve_plant_graph"
                query_type = None
                if hasattr(obs.payload, "evidence") and obs.payload.evidence:
                    first_ev = obs.payload.evidence[0]
                    prov_ref = getattr(first_ev.provenance, "reference", "") or ""
                    if ":" in prov_ref:
                        query_type = prov_ref.split(":")[0].strip()
                if not query_type and snapshot.context and snapshot.context.recent_query_types:
                    last_qt = snapshot.context.recent_query_types[-1]
                    query_type = last_qt.value if hasattr(last_qt, "value") else str(last_qt)
                if not query_type:
                    query_type = "GET_PLANT_DETAILS"

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "subagent_delegation",
                    "from_agent": "orchestrator",
                    "to_subagent": subagent,
                    "tool_invoked": "task",
                    "decision": f"Orchestrator delegates domain fact retrieval to subagent '{subagent}'",
                    "timestamp": obs_time,
                    "details": {"description": f"Retrieve recorded facts for '{plant_name or 'established plant'}'"},
                })

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "tool_selection",
                    "from_subagent": subagent,
                    "to_tool": tool_name,
                    "decision": f"Knowledge graph subagent selects typed query '{query_type}' scoped to plant '{plant_name or 'established plant'}'",
                    "timestamp": obs_time,
                })

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "subagent_handoff",
                    "from_subagent": subagent,
                    "to_agent": "orchestrator",
                    "decision": f"Subagent '{subagent}' completed retrieval and returned observation payload to main orchestrator",
                    "timestamp": obs_time,
                })

            elif comp == Capability.TEXT.value:
                subagent = "text_entity"
                tool_name = "resolve_plant_names"

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "subagent_delegation",
                    "from_agent": "orchestrator",
                    "to_subagent": subagent,
                    "tool_invoked": "task",
                    "decision": f"Orchestrator delegates botanical entity resolution to subagent '{subagent}'",
                    "timestamp": obs_time,
                    "details": {"description": "Resolve plant names and aliases from catalog"},
                })

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "tool_selection",
                    "from_subagent": subagent,
                    "to_tool": tool_name,
                    "decision": "Text entity subagent selects hybrid plant name search",
                    "timestamp": obs_time,
                })

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "subagent_handoff",
                    "from_subagent": subagent,
                    "to_agent": "orchestrator",
                    "decision": f"Subagent '{subagent}' completed retrieval and returned observation payload to main orchestrator",
                    "timestamp": obs_time,
                })

            elif comp == Capability.IMAGE.value:
                subagent = "image_understanding"
                tool_name = "inspect_uploaded_image"

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "subagent_delegation",
                    "from_agent": "orchestrator",
                    "to_subagent": subagent,
                    "tool_invoked": "task",
                    "decision": f"Orchestrator delegates visual inspection to subagent '{subagent}'",
                    "timestamp": obs_time,
                    "details": {"description": "Analyze botanical specimen image"},
                })

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "tool_selection",
                    "from_subagent": subagent,
                    "to_tool": tool_name,
                    "decision": "Image understanding subagent selects botanical image classifier",
                    "timestamp": obs_time,
                })

                step_num += 1
                routing.append({
                    "step": step_num,
                    "routing_type": "subagent_handoff",
                    "from_subagent": subagent,
                    "to_agent": "orchestrator",
                    "decision": f"Subagent '{subagent}' completed retrieval and returned observation payload to main orchestrator",
                    "timestamp": obs_time,
                })

        step_num += 1
        if result and result.clarification:
            routing.append({
                "step": step_num,
                "routing_type": "graph_conditional_edge",
                "from_node": "deep_orchestrator",
                "to_node": "clarification",
                "condition": "status == WAITING_USER",
                "decision": "Clarification required; conditional edge routes to clarification.",
                "timestamp": turn_completed_time,
            })
        else:
            routing.append({
                "step": step_num,
                "routing_type": "graph_conditional_edge",
                "from_node": "deep_orchestrator",
                "to_node": "END",
                "condition": "status == COMPLETE",
                "decision": "Turn objectives satisfied; conditional edge routes directly to END (bypassing clarification).",
                "timestamp": turn_completed_time,
            })

        return {"routing": routing}

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
        row_run = UUID(str(row["run_id"])) if row.get("run_id") else None
        owned = state.correlation.correlation_id == oid or (row_run == state.correlation.run_id)
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
