"""Central capability inputs and discriminated result payloads."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from backend.contracts.actions import AgentInvocation, Capability
from backend.contracts.base import Confidence, Contract, EntityId
from backend.contracts.evidence import Contradiction, Evidence, EvidenceGap, Provenance


class QueryType(StrEnum):
    GET_PLANT_DETAILS = "GET_PLANT_DETAILS"
    GET_PLANT_PARTS = "GET_PLANT_PARTS"
    GET_PLANT_PART_DETAILS = "GET_PLANT_PART_DETAILS"
    GET_PHYTOCHEMICALS = "GET_PHYTOCHEMICALS"
    GET_PHYTOCHEMICAL_DETAILS = "GET_PHYTOCHEMICAL_DETAILS"
    GET_BIOACTIVITY = "GET_BIOACTIVITY"
    GET_PROTEIN_TARGETS = "GET_PROTEIN_TARGETS"
    GET_THERAPEUTIC_USES = "GET_THERAPEUTIC_USES"
    GET_DOCUMENTS = "GET_DOCUMENTS"
    GET_EVIDENCE = "GET_EVIDENCE"
    GET_PLANTS_CONTAINING_COMPOUND = "GET_PLANTS_CONTAINING_COMPOUND"
    GET_COMPOUNDS_TARGETING_PROTEIN = "GET_COMPOUNDS_TARGETING_PROTEIN"
    GET_PLANTS_FOR_THERAPEUTIC_USE = "GET_PLANTS_FOR_THERAPEUTIC_USE"
    COMPARE_PLANTS = "COMPARE_PLANTS"
    TRACE_EVIDENCE = "TRACE_EVIDENCE"


class GraphParameters(Contract):
    plant_id: EntityId | None = None
    part_id: EntityId | None = None
    compound_id: EntityId | None = None
    target_id: EntityId | None = None
    therapeutic_use_id: EntityId | None = None
    evidence_id: EntityId | None = None
    comparison_plant_id: EntityId | None = None
    activity_id: EntityId | None = None
    document_id: EntityId | None = None


class GraphQuery(Contract):
    query_type: QueryType
    parameters: GraphParameters
    limit: int = Field(default=20, ge=1, le=100)
    timeout_seconds: float = Field(default=5, gt=0, le=30)
    read_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        required = {
            QueryType.GET_PLANT_PART_DETAILS: "part_id",
            QueryType.GET_PHYTOCHEMICAL_DETAILS: "compound_id",
            QueryType.GET_PLANTS_CONTAINING_COMPOUND: "compound_id",
            QueryType.GET_COMPOUNDS_TARGETING_PROTEIN: "target_id",
            QueryType.GET_PLANTS_FOR_THERAPEUTIC_USE: "therapeutic_use_id",
            QueryType.TRACE_EVIDENCE: "evidence_id",
        }.get(self.query_type, "plant_id")
        if getattr(self.parameters, required) is None:
            raise ValueError(f"{required} is required for this query")
        if self.query_type == QueryType.COMPARE_PLANTS:
            if self.parameters.comparison_plant_id is None:
                raise ValueError("comparison_plant_id is required")
        return self


class CandidatePlant(Contract):
    plant_id: EntityId
    label: str = Field(min_length=1, max_length=200)
    confidence: Confidence
    provenance: list[Provenance] = Field(default_factory=list)
    match_method: str | None = None
    matched_name: str | None = None
    language: str | None = None
    alias_type: str | None = None


class ImageMetadata(Contract):
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    size_bytes: int = Field(gt=0, le=5_242_880)
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)


class ImageReference(Contract):
    image_id: UUID
    metadata: ImageMetadata


class ImageQualityResult(Contract):
    checked: bool = False
    usable: bool | None = None
    is_plant: bool | None = None
    issues: list[str] = Field(default_factory=list)


class TextAgentInput(Contract):
    invocation: AgentInvocation
    text: str = Field(min_length=1, max_length=8000)
    active_plant_id: EntityId | None = None
    reassessment: bool = False
    active_plant: CandidatePlant | None = None
    excluded_plant_ids: list[EntityId] = Field(default_factory=list)


class ImageAgentInput(Contract):
    invocation: AgentInvocation
    image: ImageReference


class GraphAgentInput(Contract):
    invocation: AgentInvocation
    query: GraphQuery
    objective_ids: list[UUID] = Field(default_factory=list, max_length=20)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list, max_length=20)
    prior_evidence: list[Evidence] = Field(default_factory=list, max_length=100)


class ResolvedMention(Contract):
    entity_id: EntityId
    kind: Literal["compound", "therapeutic_use", "target"]
    label: str
    confidence: Confidence


class TextResult(Contract):
    kind: Literal["text"] = "text"
    candidates: list[CandidatePlant] = Field(default_factory=list, max_length=20)
    placeholder: bool = True
    intent: str = "DISCOVER_PLANT"
    query_types: list[QueryType] = Field(default_factory=list)
    part: str | None = None
    stages: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    safety_abstention: bool = False
    intent_uncertain: bool = False
    clarification_question: str | None = None
    queries: list[GraphQuery] = Field(default_factory=list, max_length=8)
    entities: list[ResolvedMention] = Field(default_factory=list, max_length=20)
    scope_rejected: bool = False


class ImageAgentResult(Contract):
    kind: Literal["image"] = "image"
    candidates: list[CandidatePlant] = Field(default_factory=list, max_length=20)
    alternatives: list[CandidatePlant] = Field(default_factory=list, max_length=20)
    plant_part: str | None = None
    quality: ImageQualityResult = Field(default_factory=ImageQualityResult)
    placeholder: bool = True


class GraphAgentOutput(Contract):
    kind: Literal["graph"] = "graph"
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    gaps: list[EvidenceGap] = Field(default_factory=list, max_length=20)
    contradictions: list[Contradiction] = Field(default_factory=list, max_length=20)
    completed_objectives: list[UUID] = Field(default_factory=list, max_length=20)
    placeholder: bool = True
    truncated: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=20)


class Observation(Contract):
    observation_id: UUID = Field(default_factory=uuid4)
    invocation: AgentInvocation
    component: Capability
    payload: Annotated[
        TextResult | ImageAgentResult | GraphAgentOutput, Field(discriminator="kind")
    ]
    confidence: Confidence = 0
    evidence_refs: list[UUID] = Field(default_factory=list)
    provenance_refs: list[EntityId] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_payload(self) -> Self:
        if self.component.value != self.payload.kind:
            raise ValueError("Observation modality does not match its payload")
        if self.payload.placeholder:
            if isinstance(self.payload, GraphAgentOutput):
                if self.payload.evidence or self.payload.completed_objectives:
                    raise ValueError("Placeholder cannot claim evidence or completion")
            elif self.payload.candidates:
                raise ValueError("Placeholder cannot claim predictions")
        return self


class FailureType(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    POLICY_REJECTION = "policy_rejection"
    UNSUPPORTED_OPERATION = "unsupported_operation"


class Failure(Contract):
    failure_id: UUID = Field(default_factory=uuid4)
    invocation: AgentInvocation
    error_type: FailureType
    reason: str = Field(max_length=500)
    retryable: bool = False
    metadata: dict[str, str | int | bool] = Field(default_factory=dict)
