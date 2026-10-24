"""Data loading and correlation from PostgreSQL persistence and memory."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from evaluation.canonical_extractor import extract_evaluation_turn
from evaluation.config import EvaluationConfig
from evaluation.models import EvaluationTurn, MetricDiagnostic


class PostgresEvaluationLoader:
    """Loads and correlates domain_trace and app_turn from PostgreSQL using asyncpg."""

    def __init__(self, config: EvaluationConfig) -> None:
        self.config = config
        self.pool: asyncpg.Pool | None = None

    async def open(self) -> None:
        if self.pool is not None:
            return
        if not self.config.database_url:
            raise RuntimeError("Database URL not configured for PostgresEvaluationLoader.")

        self.pool = await asyncpg.create_pool(
            self.config.database_url.get_secret_value(),
            min_size=1,
            max_size=self.config.postgres_pool_size,
            timeout=self.config.store_timeout_seconds,
            command_timeout=self.config.store_timeout_seconds,
        )

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def load_turns(
        self,
        session_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int | None = None,
    ) -> list[EvaluationTurn]:
        """Load turns by correlating app_turn and domain_trace records."""
        if self.pool is None:
            await self.open()

        effective_limit = min(
            limit or self.config.store_max_records, self.config.store_max_records
        )
        assert self.pool is not None

        # Build parameterized query for app_turn
        where_clauses = []
        params: list[Any] = []
        if run_id:
            params.append(run_id)
            where_clauses.append(f"run_id = ${len(params)}")
        if session_id:
            params.append(session_id)
            where_clauses.append(f"session_id = ${len(params)}")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = (
            f"SELECT run_id, session_id, state, created_at FROM app_turn "
            f"{where_sql} ORDER BY created_at DESC LIMIT {effective_limit}"
        )

        async with self.pool.acquire() as conn:
            app_rows = await conn.fetch(sql, *params)

        turns: list[EvaluationTurn] = []
        for row in app_rows:
            turn_run_id = row["run_id"]
            turn_session_id = row["session_id"]
            created_at = row["created_at"]
            raw_state = row["state"]

            # Parse state if returned as string
            state_dict: dict[str, Any]
            if isinstance(raw_state, str):
                try:
                    state_dict = json.loads(raw_state)
                except Exception as exc:
                    turns.append(
                        EvaluationTurn(
                            run_id=turn_run_id,
                            session_id=turn_session_id,
                            user_message="",
                            status="CORRUPT_STATE_JSON",
                            created_at=created_at,
                            diagnostics=[
                                MetricDiagnostic(
                                    code="JSON_PARSE_ERROR",
                                    message=f"Failed to parse app_turn state JSON: {exc}",
                                )
                            ],
                        )
                    )
                    continue
            elif isinstance(raw_state, dict):
                state_dict = raw_state
            else:
                turns.append(
                    EvaluationTurn(
                        run_id=turn_run_id,
                        session_id=turn_session_id,
                        user_message="",
                        status="INVALID_STATE_TYPE",
                        created_at=created_at,
                        diagnostics=[
                            MetricDiagnostic(
                                code="INVALID_STATE_TYPE",
                                message=f"Unexpected app_turn state type: {type(raw_state)}",
                            )
                        ],
                    )
                )
                continue

            turn = extract_evaluation_turn(
                run_id=turn_run_id,
                session_id=turn_session_id,
                state=state_dict,
                created_at=created_at,
            )
            turns.append(turn)

        return turns


class InMemoryEvaluationLoader:
    """In-memory loader for fixtures, unit testing, and offline batches."""

    def __init__(
        self,
        app_turns: list[dict[str, Any]] | None = None,
        traces: list[dict[str, Any]] | None = None,
    ) -> None:
        self.app_turns = app_turns or []
        self.traces = traces or []

    def load_turns(
        self,
        session_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> list[EvaluationTurn]:
        """Convert in-memory app_turn dictionaries into EvaluationTurns."""
        turns: list[EvaluationTurn] = []

        for row in self.app_turns:
            try:
                row_run_id = UUID(str(row["run_id"]))
                row_session_id = UUID(str(row["session_id"]))
            except (ValueError, KeyError) as exc:
                turns.append(
                    EvaluationTurn(
                        run_id=UUID("00000000-0000-0000-0000-000000000000"),
                        session_id=UUID("00000000-0000-0000-0000-000000000000"),
                        user_message="",
                        status="CORRUPT_IDENTIFIERS",
                        diagnostics=[
                            MetricDiagnostic(
                                code="IDENTIFIER_PARSE_ERROR",
                                message=f"Failed to parse UUID in fixture: {exc}",
                            )
                        ],
                    )
                )
                continue

            if run_id and row_run_id != run_id:
                continue
            if session_id and row_session_id != session_id:
                continue

            created_at: datetime | None = None
            if "created_at" in row and row["created_at"]:
                if isinstance(row["created_at"], datetime):
                    created_at = row["created_at"]
                elif isinstance(row["created_at"], str):
                    try:
                        created_at = datetime.fromisoformat(row["created_at"])
                    except ValueError:
                        pass

            state = row.get("state")
            if state is None:
                # Explicit missing app_turn state
                turns.append(
                    EvaluationTurn(
                        run_id=row_run_id,
                        session_id=row_session_id,
                        user_message="",
                        status="MISSING_APP_TURN",
                        created_at=created_at,
                        diagnostics=[
                            MetricDiagnostic(
                                code="MISSING_APP_TURN",
                                message=(
                                    "Turn record exists but state payload is missing or incomplete."
                                ),
                                details={"run_id": str(row_run_id)},
                            )
                        ],
                    )
                )
                continue

            if isinstance(state, str):
                try:
                    state = json.loads(state)
                except Exception as exc:
                    turns.append(
                        EvaluationTurn(
                            run_id=row_run_id,
                            session_id=row_session_id,
                            user_message="",
                            status="CORRUPT_STATE_JSON",
                            created_at=created_at,
                            diagnostics=[
                                MetricDiagnostic(
                                    code="JSON_PARSE_ERROR",
                                    message=f"Failed to parse state JSON: {exc}",
                                )
                            ],
                        )
                    )
                    continue

            turn = extract_evaluation_turn(
                run_id=row_run_id,
                session_id=row_session_id,
                state=state,
                created_at=created_at,
            )
            turns.append(turn)

        return turns
