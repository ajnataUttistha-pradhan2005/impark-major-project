"""Groundedness and Hallucination Rate metrics and Claim Evaluator protocol.

Metric definitions:
Groundedness (G) = supported_claims / evaluable_claims
Hallucination Rate (HR) = unsupported_claims / evaluable_claims

Guarantees & Semantics:
- Citation coverage or evidence presence is NOT treated as claim-level groundedness.
- When an offline claim evaluator is unconfigured, both metrics return None with a
  NOT_CONFIGURED diagnostic.
- When an evaluator is available:
    G + HR = 1.0 is guaranteed across all non-empty evaluable claim sets.
- If an evaluator encounters an error, claims are marked un-evaluable with an
  EVALUATOR_FAILED diagnostic; claims are never marked unsupported due to evaluator failure.
- If a turn produces only non-factual or un-evaluable claims, both metrics return None
  with a NO_EVALUABLE_CLAIMS diagnostic.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from evaluation.models import (
    ClaimEvaluationStatus,
    EvaluationTurn,
    GeneratedClaim,
    MetricDiagnostic,
)


class ClaimEvaluationResult(BaseModel):
    """Output produced by a claim evaluator for a turn."""

    status: ClaimEvaluationStatus
    claims: list[GeneratedClaim] = Field(default_factory=list)
    error_message: str | None = None


@runtime_checkable
class ClaimEvaluator(Protocol):
    """Protocol for offline claim decomposition and verification components."""

    async def evaluate_turn_claims(self, turn: EvaluationTurn) -> ClaimEvaluationResult:
        """Extract and verify claims from a turn's response and retrieved evidence."""
        ...


class NullClaimEvaluator:
    """Default evaluator used when no offline claim evaluator is configured."""

    async def evaluate_turn_claims(self, turn: EvaluationTurn) -> ClaimEvaluationResult:
        return ClaimEvaluationResult(
            status=ClaimEvaluationStatus.NOT_CONFIGURED,
            claims=[],
            error_message="No offline claim evaluator is configured.",
        )


def calculate_claim_metrics(
    eval_result: ClaimEvaluationResult,
) -> tuple[
    float | None,  # groundedness
    float | None,  # hallucination_rate
    int,  # total_claims
    int,  # evaluable_claims
    int,  # supported_claims
    int,  # unsupported_claims
    list[MetricDiagnostic],
]:
    """Calculate groundedness and hallucination rate from claim evaluation output.

    Returns:
        (groundedness, hallucination_rate, total_claims, evaluable_claims,
         supported_claims, unsupported_claims, diagnostics)
    """
    diagnostics: list[MetricDiagnostic] = []

    if eval_result.status == ClaimEvaluationStatus.NOT_CONFIGURED:
        diagnostics.append(
            MetricDiagnostic(
                code="NOT_CONFIGURED",
                message=(
                    "Offline claim evaluator is not configured. Groundedness and "
                    "hallucination rate cannot be computed deterministically from raw trace alone."
                ),
            )
        )
        return None, None, 0, 0, 0, 0, diagnostics

    if eval_result.status == ClaimEvaluationStatus.EVALUATOR_FAILED:
        total = len(eval_result.claims)
        err = eval_result.error_message or "Unknown error"
        diagnostics.append(
            MetricDiagnostic(
                code="EVALUATOR_FAILED",
                message=f"Claim evaluator failed during execution: {err}",
                details={"error": eval_result.error_message},
            )
        )
        return None, None, total, 0, 0, 0, diagnostics

    claims = eval_result.claims
    total_claims = len(claims)

    # Evaluable claims must have an explicit boolean is_supported judgment
    evaluable = [c for c in claims if c.is_supported is not None]
    evaluable_count = len(evaluable)

    if evaluable_count == 0:
        diagnostics.append(
            MetricDiagnostic(
                code="NO_EVALUABLE_CLAIMS",
                message="Turn contains no evaluable factual claims.",
                details={"total_claims": total_claims},
            )
        )
        return None, None, total_claims, 0, 0, 0, diagnostics

    supported = [c for c in evaluable if c.is_supported is True]
    unsupported = [c for c in evaluable if c.is_supported is False]

    supported_count = len(supported)
    unsupported_count = len(unsupported)

    groundedness = supported_count / evaluable_count
    hallucination_rate = unsupported_count / evaluable_count

    return (
        groundedness,
        hallucination_rate,
        total_claims,
        evaluable_count,
        supported_count,
        unsupported_count,
        diagnostics,
    )
