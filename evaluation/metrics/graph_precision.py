"""Graph retrieval precision metric.

Metric definition:
P_graph = |retrieved ∩ relevant| / |retrieved|

Conventions and Boundary Conditions:
- When |retrieved| > 0:
    Returns the fraction of retrieved canonical nodes that match relevant ground-truth nodes.
- When |retrieved| == 0 and |relevant| == 0:
    Returns 1.0 under the explicitly documented convention that the retrieval system correctly
    abstained from returning graph nodes when none were expected. A diagnostic of
    EMPTY_EMPTY_PRECISION is recorded.
- When |retrieved| == 0 and |relevant| > 0:
    Returns None (undefined precision, rather than a misleading 0.0) with a diagnostic
    of ZERO_RETRIEVAL to reflect retrieval omission without skewing precision denominators.
"""

from evaluation.models import CanonicalNodeKey, MetricDiagnostic


def calculate_graph_precision(
    retrieved_nodes: set[CanonicalNodeKey],
    relevant_nodes: set[CanonicalNodeKey],
) -> tuple[float | None, list[MetricDiagnostic]]:
    """Calculate the precision of retrieved Neo4j canonical entities against ground truth.

    Args:
        retrieved_nodes: Canonical business keys extracted from app_turn evidence.
        relevant_nodes: Canonical business keys defined in ground truth.

    Returns:
        (precision_value, diagnostics)
    """
    diagnostics: list[MetricDiagnostic] = []

    if len(retrieved_nodes) > 0:
        intersection = retrieved_nodes & relevant_nodes
        precision = len(intersection) / len(retrieved_nodes)
        return precision, diagnostics

    # Both sets are empty
    if len(relevant_nodes) == 0:
        diagnostics.append(
            MetricDiagnostic(
                code="EMPTY_EMPTY_PRECISION",
                message=(
                    "Both retrieved and relevant graph node sets are empty. "
                    "Precision assigned 1.0 under documented correct-abstention convention."
                ),
            )
        )
        return 1.0, diagnostics

    # Zero retrieval when relevant nodes were expected
    diagnostics.append(
        MetricDiagnostic(
            code="ZERO_RETRIEVAL",
            message=(
                "No graph nodes were retrieved, but relevant nodes were expected. "
                "Precision returned as None."
            ),
            details={"relevant_count": len(relevant_nodes)},
        )
    )
    return None, diagnostics
