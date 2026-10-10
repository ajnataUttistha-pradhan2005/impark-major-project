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
    # Application provenance, never inferred Neo4j node properties.
    graph_path: list[str] = Field(default_factory=list, max_length=8)
    source_urls: list[str] = Field(default_factory=list, max_length=20)
    graph_scope: dict[str, str] = Field(default_factory=dict)
    graph_nodes: list[dict[str, str | int | float | None]] = Field(
        default_factory=list, max_length=8
    )
    # Each link contains [source node index, relationship type, target node index].
    graph_links: list[tuple[int, str, int]] = Field(default_factory=list, max_length=8)


class EvidenceGap(Contract):
    objective_id: UUID
    description: str = Field(max_length=500)
    recoverable: bool = True


class Contradiction(Contract):
    entity_ids: list[EntityId]
    evidence_refs: list[UUID] = Field(default_factory=list)
    reason: str = Field(max_length=500)
    reconciled: bool = False
    affects_identity: bool = True


class EvidenceState(Contract):
    text: list[Evidence] = Field(default_factory=list)
    image: list[Evidence] = Field(default_factory=list)
    graph: list[Evidence] = Field(default_factory=list)
    gaps: list[EvidenceGap] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)

    def all_evidence(self) -> list[Evidence]:
        return [*self.text, *self.image, *self.graph]
