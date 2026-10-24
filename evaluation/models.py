"""Canonical data models for the standalone evaluation service."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_serializer


class Capability(StrEnum):
    """Recognized agent capability domains."""

    TEXT = "text"
    IMAGE = "image"
    GRAPH = "graph"


class GraphEntityType(StrEnum):
    """Categorized Neo4j node business domains."""

    PLANT = "plant"
    PLANT_ALIAS = "plant_alias"
    PLANT_PART = "plant_part"
    COMPOUND = "compound"
    BIOACTIVITY = "bioactivity"
    PROTEIN_TARGET = "protein_target"
    DOCUMENT = "document"
    THERAPEUTIC_USE = "therapeutic_use"
    UNKNOWN = "unknown"


class ClaimEvaluationStatus(StrEnum):
    """Lifecycle status for claim-level groundedness and hallucination evaluation."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    EVALUATOR_FAILED = "EVALUATOR_FAILED"
    NO_EVALUABLE_CLAIMS = "NO_EVALUABLE_CLAIMS"
    EVALUATED = "EVALUATED"


class CanonicalNodeKey(BaseModel):
    """Business identity of a Neo4j node, independent of transient evidence UUIDs."""

    entity_type: GraphEntityType
    business_id: str

    def __hash__(self) -> int:
        return hash((self.entity_type, self.business_id))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CanonicalNodeKey):
            return False
        return (self.entity_type, self.business_id) == (other.entity_type, other.business_id)

    def to_tuple(self) -> tuple[str, str]:
        return (self.entity_type.value, self.business_id)


class RoutingObservation(BaseModel):
    """Step in an observed multi-agent execution path."""

    step_index: int
    capability: Capability
    action_name: str
    component_raw: str = ""


class GeneratedClaim(BaseModel):
    """Structured representation of an individual claim in a generated response."""

    claim_id: UUID = Field(default_factory=uuid4)
    text: str
    cited_evidence_ids: list[UUID] = Field(default_factory=list)
    is_supported: bool | None = None
    verification_rationale: str | None = None


class GeneratedResponse(BaseModel):
    """Persisted answer generated during a turn."""

    text: str
    citation_ids: list[UUID] = Field(default_factory=list)
    provider: str = ""
    model: str | None = None
    claims_available: bool = False
    claims: list[GeneratedClaim] = Field(default_factory=list)


class MetricDiagnostic(BaseModel):
    """Diagnostic message for edge cases, failures, or skipped turns."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationTurn(BaseModel):
    """Normalized turn record loaded from app_turn and domain_trace."""

    run_id: UUID
    session_id: UUID
    user_message: str
    status: str
    created_at: datetime | None = None
    execution_path: list[RoutingObservation] = Field(default_factory=list)
    retrieved_graph_nodes: list[CanonicalNodeKey] = Field(default_factory=list)
    unrecognized_graph_nodes: list[dict[str, Any]] = Field(default_factory=list)
    missing_key_nodes: list[dict[str, Any]] = Field(default_factory=list)
    response: GeneratedResponse | None = None
    raw_state: dict[str, Any] | None = None
    diagnostics: list[MetricDiagnostic] = Field(default_factory=list)

    @property
    def canonical_node_set(self) -> set[CanonicalNodeKey]:
        return set(self.retrieved_graph_nodes)


class GroundTruthTestCase(BaseModel):
    """Expected evaluation criteria for a botanical turn or question."""

    case_id: str
    query_text: str | None = None
    run_id: UUID | None = None
    session_id: UUID | None = None
    target_capability: Capability
    disallowed_capabilities: list[Capability] = Field(default_factory=lambda: [Capability.IMAGE])
    relevant_nodes: list[CanonicalNodeKey] = Field(default_factory=list)
    ground_truth_claims: list[str] | None = None

    @property
    def relevant_node_set(self) -> set[CanonicalNodeKey]:
        return set(self.relevant_nodes)


class TurnMetricResult(BaseModel):
    """Evaluation outcomes for an individual turn."""

    run_id: UUID | None = None
    session_id: UUID | None = None
    case_id: str | None = None
    user_message_sample: str = ""

    # Routing Compliance
    routing_compliant: bool | None = None
    target_capability: Capability | None = None
    observed_path: list[str] = Field(default_factory=list)

    # Graph Retrieval Precision
    graph_precision: float | None = None
    retrieved_nodes_count: int = 0
    relevant_nodes_count: int = 0
    retrieved_nodes: list[CanonicalNodeKey] = Field(default_factory=list)
    relevant_nodes: list[CanonicalNodeKey] = Field(default_factory=list)

    # Claim Groundedness and Hallucination
    groundedness: float | None = None
    hallucination_rate: float | None = None
    total_claims_count: int = 0
    evaluable_claims_count: int = 0
    supported_claims_count: int = 0
    unsupported_claims_count: int = 0

    diagnostics: list[MetricDiagnostic] = Field(default_factory=list)


class CoverageSummary(BaseModel):
    """Accounting of turns and claims evaluated, skipped, or missing."""

    total_cases: int = 0
    matched_turns: int = 0
    missing_turns: int = 0
    incomplete_turns: int = 0
    evaluated_turns: int = 0
    skipped_turns: int = 0
    turn_coverage: float = 0.0

    total_claims: int = 0
    evaluable_claims: int = 0
    skipped_claims: int = 0
    claim_coverage: float = 0.0


class EvaluationResult(BaseModel):
    """Aggregate evaluation report produced by the service."""

    evaluation_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Core Aggregate Metrics (Nullable when genuinely uncomputable)
    routing_accuracy: float | None = None
    graph_precision: float | None = None
    groundedness: float | None = None
    hallucination_rate: float | None = None

    coverage: CoverageSummary
    turn_results: list[TurnMetricResult] = Field(default_factory=list)
    diagnostics: list[MetricDiagnostic] = Field(default_factory=list)
    data_sources_used: dict[str, bool] = Field(
        default_factory=lambda: {
            "domain_trace": True,
            "app_turn": True,
            "ground_truth": True,
        }
    )

    @field_serializer("created_at")
    def serialize_datetime(self, dt: datetime) -> str:
        return dt.isoformat()
