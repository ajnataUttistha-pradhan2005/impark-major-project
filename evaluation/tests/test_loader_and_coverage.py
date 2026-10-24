"""Tests for data loading, ground truth correlation, and coverage accounting."""

from pathlib import Path
from uuid import uuid4

import pytest

from evaluation.ground_truth import GroundTruthMatcher, load_ground_truth_file
from evaluation.loader import InMemoryEvaluationLoader
from evaluation.models import Capability, EvaluationTurn, GroundTruthTestCase
from evaluation.service import EvaluationService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_load_ground_truth_json():
    """Verify loading and parsing of ground truth JSON fixture."""
    cases = load_ground_truth_file(FIXTURES_DIR / "sample_ground_truth.json")
    assert len(cases) == 3
    c1 = cases[0]
    assert c1.case_id == "case-01"
    assert c1.target_capability == Capability.GRAPH
    assert len(c1.relevant_nodes) == 3


def test_load_ground_truth_yaml():
    """Verify loading and parsing of ground truth YAML fixture."""
    cases = load_ground_truth_file(FIXTURES_DIR / "sample_ground_truth.yaml")
    assert len(cases) == 1
    c = cases[0]
    assert c.case_id == "case-yaml-01"
    assert c.target_capability == Capability.GRAPH
    assert len(c.relevant_nodes) == 1


def test_in_memory_loader_handles_missing_app_turn_state():
    """Verify missing app_turn record produces diagnostic and does not crash."""
    loader = InMemoryEvaluationLoader(
        app_turns=[
            {
                "run_id": "11111111-1111-1111-1111-111111111111",
                "session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "state": None,  # State is missing
            }
        ]
    )
    turns = loader.load_turns()
    assert len(turns) == 1
    assert turns[0].status == "MISSING_APP_TURN"
    assert len(turns[0].diagnostics) == 1
    assert turns[0].diagnostics[0].code == "MISSING_APP_TURN"


def test_in_memory_loader_handles_corrupt_json():
    """Verify corrupt JSON state is handled gracefully with diagnostic."""
    loader = InMemoryEvaluationLoader(
        app_turns=[
            {
                "run_id": "11111111-1111-1111-1111-111111111111",
                "session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "state": "{broken_json",
            }
        ]
    )
    turns = loader.load_turns()
    assert len(turns) == 1
    assert turns[0].status == "CORRUPT_STATE_JSON"
    assert turns[0].diagnostics[0].code == "JSON_PARSE_ERROR"


def test_ground_truth_matcher_priorities():
    """Verify correlation priorities: run_id, session_id, and query text."""
    run_1 = uuid4()
    run_2 = uuid4()
    session_1 = uuid4()

    turn_1 = EvaluationTurn(
        run_id=run_1,
        session_id=session_1,
        user_message="Tell me about Tulsi",
        status="COMPLETE",
    )
    turn_2 = EvaluationTurn(
        run_id=run_2,
        session_id=uuid4(),
        user_message="What is Neem?",
        status="COMPLETE",
    )

    cases = [
        # Match by run_id
        GroundTruthTestCase(case_id="c1", run_id=run_1, target_capability=Capability.TEXT),
        # Match by query text
        GroundTruthTestCase(
            case_id="c2", query_text="what is neem?", target_capability=Capability.GRAPH
        ),
        # Unmatched case
        GroundTruthTestCase(
            case_id="c3-unmatched",
            query_text="Ashwagandha uses",
            target_capability=Capability.GRAPH,
        ),
    ]

    matched, unmatched_cases, unmatched_turns = GroundTruthMatcher.match(cases, [turn_1, turn_2])

    assert len(matched) == 2
    assert matched[0][0].case_id == "c1"
    assert matched[0][1].run_id == run_1
    assert matched[1][0].case_id == "c2"
    assert matched[1][1].run_id == run_2

    assert len(unmatched_cases) == 1
    assert unmatched_cases[0].case_id == "c3-unmatched"
    assert len(unmatched_turns) == 0


@pytest.mark.asyncio
async def test_service_coverage_accounting_with_missing_cases():
    """Verify service correctly accounts for missing cases in denominator and computes coverage."""
    cases = load_ground_truth_file(FIXTURES_DIR / "sample_ground_truth.json")
    loader = InMemoryEvaluationLoader(
        app_turns=[
            {
                "run_id": "11111111-1111-1111-1111-111111111111",
                "session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "state": {
                    "user_message": "What phytochemicals are found in Neem leaves?",
                    "termination": {"status": "COMPLETE"},
                    "execution": {
                        "observations": [
                            {
                                "component": "graph",
                                "invocation": {"action": {"name": "retrieve_plant_graph"}},
                            }
                        ]
                    },
                    "evidence": {"graph": [{"graph_nodes": [{"inchi_key": "INCHI_NIMBIN_123"}]}]},
                },
            }
        ]
    )
    turns = loader.load_turns()

    service = EvaluationService()
    result = await service.evaluate_batch(turns=turns, ground_truth=cases)

    # cases has 3 items: case-01 (matched), case-02 (unmatched), case-03-missing (unmatched)
    assert result.coverage.total_cases == 3
    assert result.coverage.matched_turns == 1
    assert result.coverage.missing_turns == 2
    assert result.coverage.evaluated_turns == 1
    assert result.coverage.turn_coverage == round(1 / 3, 4)

    # Routing accuracy should be computed only over evaluated turns
    assert result.routing_accuracy == 1.0

    # Missing cases generate diagnostics
    missing_diags = [d for d in result.diagnostics if d.code == "MISSING_TURN_FOR_CASE"]
    assert len(missing_diags) == 2
