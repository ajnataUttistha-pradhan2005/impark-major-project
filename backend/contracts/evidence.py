from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from backend.contracts.base import Confidence, Contract, EntityId


class EvidenceClass(StrEnum):
    TRADITIONAL = "traditional"
    PRECLINICAL = "preclinical"
    IN_VITRO = "in-vitro"
    ANIMAL = "animal"
    CLINICAL = "clinical"
    MECHANISTIC = "mechanistic"
    ESTABLISHED = "established"
    UNKNOWN = "unknown"


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    GRAPH = "graph"


class Provenance(Contract):
    source_id: EntityId
    source_type: str
    reference: str = Field(max_length=500)
    provider_version: str | None = None


class Evidence(Contract):
    evidence_id: UUID = Field(default_factory=uuid4)
    modality: Modality
    claim: str = Field(min_length=1, max_length=4000)
    evidence_type: EvidenceClass = EvidenceClass.UNKNOWN
    confidence: Confidence
    source_quality: Confidence = 0
    provenance: Provenance
    supports: list[EntityId] = Field(default_factory=list)
    contradicts: list[EntityId] = Field(default_factory=list)
    recorded_at: datetime | None = None


class EvidenceGap(Contract):
    objective_id: UUID
    description: str = Field(max_length=500)


class Contradiction(Contract):
    entity_ids: list[EntityId]
    evidence_refs: list[UUID] = Field(default_factory=list)
    reason: str = Field(max_length=500)
    reconciled: bool = False


class EvidenceState(Contract):
    text: list[Evidence] = Field(default_factory=list)
    image: list[Evidence] = Field(default_factory=list)
    graph: list[Evidence] = Field(default_factory=list)
    gaps: list[EvidenceGap] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)

    def all_evidence(self) -> list[Evidence]:
        return [*self.text, *self.image, *self.graph]
