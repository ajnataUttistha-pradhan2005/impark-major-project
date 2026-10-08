import asyncio
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend.api.schemas.chat import AutocompleteResponse, ChatRequest, ChatResponse
from backend.config.settings import Settings
from backend.contracts.agents import ImageReference
from backend.contracts.base import CorrelationMetadata
from backend.contracts.response import ClarificationResponse
from backend.database.postgres.repositories import SessionRepository
from backend.orchestrator.graph import RuntimeState, build_graph
from backend.orchestrator.orchestrator import Harness
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
from backend.trace.models import EventType


def public_state(state: ConversationState) -> ChatResponse:
    return ChatResponse(
        correlation=state.correlation,
        mode=state.session.mode,
        status=state.termination.status,
        active_plant=state.context.active_plant,
        clarification=state.clarification,
        response=state.response,
    )


class ConversationService:
    def __init__(self, repository: SessionRepository, harness: Harness, settings: Settings) -> None:
        self.repository, self.harness, self.settings = repository, harness, settings
        self.graph = build_graph(harness, InMemorySaver())
        self.locks: dict[UUID, asyncio.Lock] = {}
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
        await self.load(session_id)
        lock = self.locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise ServiceError("CONFLICT", "Conversation already has an active turn", 409)
        async with lock:
            state = await self.load(session_id)
            waiting = state.termination.status == TaskStatus.WAITING_USER
            if waiting:
                if request.image_id is not None:
                    raise ServiceError(
                        "UNSUPPORTED_OPERATION", "Image clarification is pending", 501
                    )
                assert state.clarification is not None
                if clarification is None:
                    clarification = ClarificationResponse(
                        clarification_id=state.clarification.clarification_id,
                        text=request.text or "",
                    )
                if clarification.clarification_id != state.clarification.clarification_id:
                    raise ServiceError("CONFLICT", "Clarification checkpoint mismatch", 409)
                config = self._config(state)
                value: Command[str] = Command(resume=clarification.model_dump(mode="json"))
                with tracer.start_as_current_span("conversation.resume"):
                    result = await self.graph.ainvoke(value, config)
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
                state.image = None
                if request.image_id is not None:
                    state.image = self.images.get(session_id, {}).get(request.image_id)
                    if state.image is None:
                        raise ServiceError("INVALID_INPUT", "Unknown image for this conversation")
                # Until coreference/intent integration is implemented, new discovery input
                # must not inherit confidence from a previous plant identification.
                state.belief = BeliefState(
                    text_pending=bool(request.text), image_pending=state.image is not None
                )
                # Goal interpretation remains a Text/Entity integration TODO. Do not infer
                # graph intent from arbitrary keywords in this foundation API.
                state.goal = Goal()
                state.execution = ExecutionState()
                state.iteration = 0
                state.clarification_count = 0
                state.response = None
                state.response_context = None
                state.last_decision = None
                state.available_actions = []
                state.termination = TerminationState()
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

    @staticmethod
    def _config(state: ConversationState) -> RunnableConfig:
        return {
            "configurable": {"thread_id": str(state.correlation.run_id)},
            "recursion_limit": 150,
        }

    async def autocomplete(self, query: str) -> AutocompleteResponse:
        return AutocompleteResponse()
