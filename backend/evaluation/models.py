from typing import Protocol
from uuid import UUID

from pydantic import Field

from backend.contracts.actions import ActionName
from backend.contracts.base import Contract
from backend.trace.models import TraceEvent


class EvaluationCase(Contract):
    case_id: str
    allowed_actions: list[ActionName]
    forbidden_actions: list[ActionName] = Field(default_factory=list)


class EvaluationResult(Contract):
    case_id: str
    run_id: UUID
    passed: bool
    metrics: dict[str, float] = Field(default_factory=dict)


class EvaluationRepository(Protocol):
    async def save(self, result: EvaluationResult) -> None: ...


def iteration_snapshots(events: list[TraceEvent], run_id: UUID) -> list[TraceEvent]:
    """Offline reconstruction inputs; no dependence on a single expected route."""
    return sorted(
        [e for e in events if e.correlation.run_id == run_id and e.snapshot is not None],
        key=lambda e: (e.correlation.iteration, e.timestamp),
    )
