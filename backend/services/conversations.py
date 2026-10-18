import asyncio
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from backend.agents.text.search import HybridNameSearch
from backend.api.schemas.chat import AutocompleteResponse, ChatRequest, ChatResponse
from backend.config.settings import Settings
from backend.contracts.agents import ImageAgentResult, ImageReference, TextResult
from backend.contracts.base import CorrelationMetadata
from backend.contracts.evidence import EvidenceState
from backend.contracts.response import ClarificationResponse
from backend.database.postgres.repositories import SessionRepository
from backend.orchestrator.deepagents.graph import RuntimeState
from backend.orchestrator.deepagents.host import AgentHost
from backend.services.errors import ServiceError
from backend.state.goals import Goal
from backend.state.models import (
    BeliefState,
    ConversationState,
    ExecutionState,
    TaskStatus,
    TerminationState,
)
from backend.trace.instrumentation import tracer
from backend.trace.models import EventType, TraceEvent


def public_state(state: ConversationState) -> ChatResponse:
    return ChatResponse(
        correlation=state.correlation,
        mode=state.session.mode,
        status=state.termination.status,
        active_plant=state.context.active_plant,
        clarification=state.clarification,
        response=state.response,
        image_understanding=next(
            (
                o.payload
                for o in reversed(state.execution.observations)
                if isinstance(o.payload, ImageAgentResult)
            ),
            None,
        ),
        understanding=next(
            (
                o.payload
                for o in reversed(state.execution.observations)
                if isinstance(o.payload, TextResult)
            ),
            None,
        ),
    )


class ConversationService:
    def __init__(
        self, repository: SessionRepository, harness: AgentHost, settings: Settings
    ) -> None:
        self.repository, self.harness, self.settings = repository, harness, settings
        self.graph = None
        self.locks: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()
        self.images: dict[UUID, dict[UUID, ImageReference]] = {}

    async def create(self, correlation_id: UUID) -> ChatResponse:
        state = ConversationState.new(self.settings.budgets())
        state.correlation.correlation_id = correlation_id
        await self.repository.save(state)
        self.harness.emit(state, EventType.SESSION_CREATED)
        return public_state(state)

    async def load(self, session_id: UUID) -> ConversationState:
        state = await self.repository.get(session_id)
        if state is None:
            raise ServiceError("NOT_FOUND", "Conversation not found", 404)
        return state

    async def get(self, session_id: UUID) -> ChatResponse:
        return public_state(await self.load(session_id))

    async def history(self, session_id: UUID) -> list[ChatResponse]:
        await self.load(session_id)
        return [public_state(s) for s in await self.repository.history(session_id)]

    async def submit(
        self,
        session_id: UUID,
        request: ChatRequest,
        correlation_id: UUID,
        clarification: ClarificationResponse | None = None,
    ) -> ChatResponse:
        if not (self.settings.agent_main_model or self.settings.llm_model):
            raise ServiceError("UNAVAILABLE", "Response model is not configured", 503)
        await self.load(session_id)
        lock = self.locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise ServiceError("CONFLICT", "Conversation already has an active turn", 409)
        async with lock:
            state = await self.load(session_id)
            if state.context.active_plant and state.session.locked_plant_id is None:
                state.session.locked_plant_id = state.context.active_plant.plant_id
            selected_id = (clarification.selected_plant_id if clarification else None) or (
                str(request.selected_plant_id) if request.selected_plant_id else None
            )
            if selected_id and state.session.locked_plant_id not in {None, selected_id}:
                raise ServiceError(
                    "PLANT_SCOPE_LOCKED", "One plant per chat. Start a new chat.", 409
                )
            if state.termination.status == TaskStatus.RUNNING:
                raise ServiceError("CONFLICT", "Interrupted turn requires resume", 409)
            waiting = state.termination.status == TaskStatus.WAITING_USER
            if waiting:
                replacement = None
                if request.image_id is not None:
                    replacement = self.images.get(session_id, {}).get(request.image_id)
                    if replacement is None or selected_id:
                        raise ServiceError(
                            "INVALID_INPUT", "Provide a registered image or a selection"
                        )
                assert state.clarification is not None
                if clarification is None:
                    clarification = ClarificationResponse(
                        clarification_id=state.clarification.clarification_id,
                        text=request.text or "Updated image",
                        image_id=request.image_id,
                    )
                if clarification.clarification_id != state.clarification.clarification_id:
                    raise ServiceError("CONFLICT", "Clarification checkpoint mismatch", 409)
                from backend.orchestrator.deepagents.clarification import apply_clarification

                checked = state.model_copy(deep=True)
                try:
                    apply_clarification(checked, clarification, replacement)
                except ValueError:
                    raise ServiceError("INVALID_INPUT", "Select an offered candidate") from None
                config = self._config(state)
                resume_payload = clarification.model_dump(mode="json")
                if replacement is not None:
                    resume_payload["_image"] = replacement.model_dump(mode="json")
                value: Command[str] = Command(resume=resume_payload)
                with tracer.start_as_current_span("conversation.resume"):
                    checkpoint = await self.graph.aget_state(config)
                    # Mark accepted input before executing; cancellation can resume this run.
                    await self.repository.save(checked)
                    if checkpoint.values:
                        result = await self.graph.ainvoke(value, config)
                    else:
                        # Restart recovery from durable interrupted application state.
                        # Preserve run/turn lineage and budgets; never resume a fresh task.
                        self.harness.emit(checked, EventType.EXECUTION_RESUMED)
                        result = await self.graph.ainvoke(RuntimeState(domain=checked), config)
            else:
                if clarification is not None:
                    raise ServiceError("CONFLICT", "No clarification is pending", 409)
                state.correlation = CorrelationMetadata(
                    session_id=session_id,
                    turn_id=uuid4(),
                    run_id=uuid4(),
                    correlation_id=correlation_id,
                )
                state.user_message = request.text or ""
                if request.selected_plant_id:
                    provider = getattr(self.harness.execution.text, "provider", None)
                    if not isinstance(provider, HybridNameSearch):
                        raise ServiceError("UNAVAILABLE", "Entity search unavailable", 503)
                    _, records = await provider.catalog()
                    if not any(r.plant_id == request.selected_plant_id for r in records):
                        raise ServiceError("INVALID_INPUT", "Unknown candidate identifier")
                    # A verified selection is a stable identifier input to the same Text Agent.
                    selected_name = next(
                        r.plant_name for r in records if r.plant_id == request.selected_plant_id
                    )
                    state.user_message = f"{selected_name} {request.text or ''}".strip()
                    from backend.contracts.agents import CandidatePlant

                    state.context.active_plant = CandidatePlant(
                        plant_id=str(request.selected_plant_id),
                        label=selected_name,
                        confidence=1.0,
                    )
                state.image = None
                if request.image_id is not None:
                    state.image = self.images.get(session_id, {}).get(request.image_id)
                    if state.image is None:
                        raise ServiceError("INVALID_INPUT", "Unknown image for this conversation")
                # Each turn reassesses language; old evidence cannot answer a new plant's question.
                state.belief = BeliefState(
                    text_pending=bool(state.user_message), image_pending=state.image is not None
                )
                state.goal = Goal()
                state.evidence = EvidenceState()
                state.context.active_part = None
                state.execution = ExecutionState()
                state.iteration = 0
                state.clarification_count = 0
                state.response = None
                state.response_context = None
                state.last_decision = None
                state.available_actions = []
                state.termination = TerminationState()
                state.termination.status = TaskStatus.RUNNING
                await self.repository.save(state)
                config = self._config(state)
                with tracer.start_as_current_span("conversation.turn"):
                    result = await self.graph.ainvoke(RuntimeState(domain=state), config)
            updated = result["domain"]
            state = (
                updated
                if isinstance(updated, ConversationState)
                else ConversationState.model_validate(updated)
            )
            await self.repository.save(state)
            return public_state(state)

    async def recover(self, session_id: UUID) -> ChatResponse:
        """Explicitly continue a persisted interrupted run; replayed agents must be read-only."""
        lock = self.locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise ServiceError("CONFLICT", "Conversation already has an active turn", 409)
        async with lock:
            state = await self.load(session_id)
            if state.termination.status != TaskStatus.RUNNING:
                raise ServiceError("CONFLICT", "No interrupted running turn", 409)
            config = self._config(state)
            checkpoint = await self.graph.aget_state(config)
            self.harness.emit(state, EventType.EXECUTION_RESUMED)
            result = await self.graph.ainvoke(
                None if checkpoint.values else RuntimeState(domain=state), config
            )
            updated = result["domain"]
            state = (
                updated
                if isinstance(updated, ConversationState)
                else (ConversationState.model_validate(updated))
            )
            await self.repository.save(state)
            return public_state(state)

    @staticmethod
    def _config(state: ConversationState) -> RunnableConfig:
        return {
            "configurable": {"thread_id": str(state.correlation.run_id)},
            "recursion_limit": 150,
        }

    async def autocomplete(self, query: str) -> AutocompleteResponse:
        provider = getattr(self.harness.execution.text, "provider", None)
        if not isinstance(provider, HybridNameSearch):
            return AutocompleteResponse()
        return AutocompleteResponse(
            candidates=await provider.autocomplete(query),
            implemented=True,
            detail="Suggestions do not establish identity",
        )

    async def trace_events(self, session_id: UUID) -> list["TraceEvent"]:
        from backend.database.postgres.persistence import PostgresTraceSink
        from backend.trace.recorder import MemoryTraceSink

        await self.load(session_id)
        sink = self.harness.trace.sink
        if isinstance(sink, PostgresTraceSink):
            return await sink.read_events(session_id)
        if isinstance(sink, MemoryTraceSink):
            return [e for e in sink.events if e.correlation.session_id == session_id][-200:]
        return []
