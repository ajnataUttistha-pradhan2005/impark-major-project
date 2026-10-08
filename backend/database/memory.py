from uuid import UUID

from backend.state.models import ConversationState


class MemorySessionRepository:
    """Development only: process-local, non-durable, single-worker storage."""

    def __init__(self) -> None:
        self.states: dict[UUID, ConversationState] = {}
        self.turns: dict[UUID, list[ConversationState]] = {}

    async def get(self, session_id: UUID) -> ConversationState | None:
        state = self.states.get(session_id)
        return state.model_copy(deep=True) if state is not None else None

    async def save(self, state: ConversationState) -> None:
        key = state.session.session_id
        self.states[key] = state.model_copy(deep=True)
        history = self.turns.setdefault(key, [])
        if state.correlation.run_id is not None:
            if history and history[-1].correlation.run_id == state.correlation.run_id:
                history[-1] = state.model_copy(deep=True)
            else:
                history.append(state.model_copy(deep=True))

    async def history(self, session_id: UUID) -> list[ConversationState]:
        return [s.model_copy(deep=True) for s in self.turns.get(session_id, [])]
