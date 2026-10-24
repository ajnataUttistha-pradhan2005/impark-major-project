"""Standalone Evaluation Service for IMPARK.

This package evaluates:
- Capability routing compliance (presence of target capability and discipline)
- Graph retrieval precision (based on canonical Neo4j business keys)
- Groundedness and Hallucination Rate (pluggable offline claim evaluator)
"""

from evaluation.config import EvaluationConfig
from evaluation.models import (
    CanonicalNodeKey,
    Capability,
    EvaluationResult,
    EvaluationTurn,
    GeneratedClaim,
    GeneratedResponse,
    GraphEntityType,
    GroundTruthTestCase,
    MetricDiagnostic,
    RoutingObservation,
    TurnMetricResult,
)
from evaluation.service import EvaluationService

__all__ = [
    "CanonicalNodeKey",
    "Capability",
    "EvaluationConfig",
    "EvaluationResult",
    "EvaluationService",
    "EvaluationTurn",
    "GeneratedClaim",
    "GeneratedResponse",
    "GraphEntityType",
    "GroundTruthTestCase",
    "MetricDiagnostic",
    "RoutingObservation",
    "TurnMetricResult",
]
