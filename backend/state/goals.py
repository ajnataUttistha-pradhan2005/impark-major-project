from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from backend.contracts.agents import QueryType
from backend.contracts.base import Contract
from backend.contracts.evidence import Modality


class ObjectiveStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"


class Objective(Contract):
    objective_id: UUID = Field(default_factory=uuid4)
    description: str = "Establish plant identity"
    required_evidence: list[Modality] = Field(default_factory=list)
    query_type: QueryType | None = None
    status: ObjectiveStatus = ObjectiveStatus.PENDING


class Goal(Contract):
    goal_id: UUID = Field(default_factory=uuid4)
    intent: str = "DISCOVER_PLANT"
    objectives: list[Objective] = Field(default_factory=lambda: [Objective()])
    answerable_when: tuple[str, ...] = ("plant_resolved",)
    abstention_conditions: tuple[str, ...] = ("evidence_unavailable", "unsafe_request")

    @property
    def pending(self) -> list[Objective]:
        return [o for o in self.objectives if o.status == ObjectiveStatus.PENDING]

    @property
    def completed(self) -> list[Objective]:
        return [o for o in self.objectives if o.status == ObjectiveStatus.COMPLETE]
