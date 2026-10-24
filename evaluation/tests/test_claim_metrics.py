"""Tests for Groundedness, Hallucination Rate, and Claim Evaluator protocol."""

from uuid import uuid4

import pytest

from evaluation.metrics.claims import (
    ClaimEvaluationResult,
    NullClaimEvaluator,
    calculate_claim_metrics,
)
from evaluation.models import (
    ClaimEvaluationStatus,
    EvaluationTurn,
    GeneratedClaim,
)


@pytest.mark.asyncio
async def test_claim_metrics_when_evaluator_unconfigured():
    """Verify metrics return None with NOT_CONFIGURED when evaluator is not configured."""
    evaluator = NullClaimEvaluator()
    turn = EvaluationTurn(
        run_id=uuid4(),
        session_id=uuid4(),
        user_message="test",
        status="COMPLETE",
    )

    result = await evaluator.evaluate_turn_claims(turn)
    g, hr, tot, eval_c, sup, unsup, diags = calculate_claim_metrics(result)

    assert g is None
    assert hr is None
    assert tot == 0
    assert eval_c == 0
    assert len(diags) == 1
    assert diags[0].code == "NOT_CONFIGURED"


def test_claim_metrics_when_evaluator_fails():
    """Verify evaluator failures return None and do NOT mark claims unsupported."""
    claims = [
        GeneratedClaim(text="Claim 1"),
        GeneratedClaim(text="Claim 2"),
    ]
    result = ClaimEvaluationResult(
        status=ClaimEvaluationStatus.EVALUATOR_FAILED,
        claims=claims,
        error_message="API connection timeout",
    )

    g, hr, tot, eval_c, sup, unsup, diags = calculate_claim_metrics(result)

    assert g is None
    assert hr is None
    assert tot == 2
    assert eval_c == 0
    assert sup == 0
    assert unsup == 0  # CRITICAL: not marked unsupported due to evaluator error
    assert len(diags) == 1
    assert diags[0].code == "EVALUATOR_FAILED"


def test_claim_metrics_when_no_evaluable_claims():
    """Verify returns None when turn has no evaluable claims."""
    # Claims where is_supported is None (e.g. conversational pleasantries)
    claims = [
        GeneratedClaim(text="Hello, how can I help you?"),
        GeneratedClaim(text="I hope this information was useful."),
    ]
    result = ClaimEvaluationResult(
        status=ClaimEvaluationStatus.EVALUATED,
        claims=claims,
    )

    g, hr, tot, eval_c, sup, unsup, diags = calculate_claim_metrics(result)

    assert g is None
    assert hr is None
    assert tot == 2
    assert eval_c == 0
    assert len(diags) == 1
    assert diags[0].code == "NO_EVALUABLE_CLAIMS"


def test_claim_metrics_calculation_and_complementarity():
    """Verify G and HR are exact mathematical complements when evaluable claims exist."""
    claims = [
        GeneratedClaim(text="Fact 1", is_supported=True),
        GeneratedClaim(text="Fact 2", is_supported=True),
        GeneratedClaim(text="Fact 3", is_supported=True),
        GeneratedClaim(text="Fact 4 (hallucinated)", is_supported=False),
        GeneratedClaim(text="Conversational greeting", is_supported=None),  # skipped
    ]
    result = ClaimEvaluationResult(
        status=ClaimEvaluationStatus.EVALUATED,
        claims=claims,
    )

    g, hr, tot, eval_c, sup, unsup, diags = calculate_claim_metrics(result)

    assert tot == 5
    assert eval_c == 4
    assert sup == 3
    assert unsup == 1
    assert g == 0.75
    assert hr == 0.25
    assert g + hr == 1.0  # Mathematical complement property
    assert len(diags) == 0
