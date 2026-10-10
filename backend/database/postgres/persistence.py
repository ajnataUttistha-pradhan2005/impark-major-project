from uuid import UUID

from backend.database.postgres.client import PostgresClient
from backend.state.models import ConversationState
from backend.trace.models import TraceEvent


class PostgresSessionRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    async def get(self, session_id: UUID) -> ConversationState | None:
        row = await self.client.single(
            "SELECT state FROM app_session WHERE session_id=$1", session_id
        )
        return ConversationState.model_validate_json(row["state"]) if row else None

    async def save(self, state: ConversationState) -> None:
        async with self.client.transaction(write=True) as tx:
            await tx.execute(
                "INSERT INTO app_session(session_id,state) VALUES($1,$2::jsonb) "
                "ON CONFLICT(session_id) DO UPDATE SET state=excluded.state,updated_at=now()",
                state.session.session_id,
                state.model_dump_json(),
            )
            if state.correlation.run_id:
                await tx.execute(
                    "INSERT INTO app_turn(run_id,session_id,state) VALUES($1,$2,$3::jsonb) "
                    "ON CONFLICT(run_id) DO UPDATE SET state=excluded.state",
                    state.correlation.run_id,
                    state.session.session_id,
                    state.model_dump_json(),
                )

    async def history(self, session_id: UUID) -> list[ConversationState]:
        rows = await self.client.read(
            "SELECT state FROM app_turn WHERE session_id=$1 ORDER BY created_at LIMIT 100",
            session_id,
        )
        return [ConversationState.model_validate_json(row["state"]) for row in rows]


class PostgresTraceSink:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    async def write(self, event: TraceEvent) -> None:
        await self.client.write(
            "INSERT INTO domain_trace(event_id,session_id,run_id,event_type,event) "
            "VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT(event_id) DO NOTHING",
            event.event_id,
            event.correlation.session_id,
            event.correlation.run_id,
            event.event_type.value,
            event.model_dump_json(),
        )

    async def read_events(self, session_id: UUID, limit: int = 200) -> list[TraceEvent]:
        rows = await self.client.read(
            "SELECT event FROM domain_trace WHERE session_id=$1 ORDER BY created_at DESC LIMIT $2",
            session_id,
            limit,
        )
        return [TraceEvent.model_validate_json(row["event"]) for row in reversed(rows)]
