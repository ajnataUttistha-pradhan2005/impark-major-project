"""Unit tests for the IMPARK Ground-Truth Generation and Metric Evaluation Pipeline.

Covers:
- Identifier parsing
- Case-key construction and slugification
- Text normalization
- Ground-truth status assignment
- Metric denominator handling (N/A when denominator is zero)
- Leaf scope enforcement
- Trace completeness
"""

from __future__ import annotations

import pytest

from scripts.generate_ground_truth import (
    GroundTruthCase,
    normalize_text,
    parse_identifier_list,
    slugify,
)
from scripts.evaluate_existing_runs import (
    CaseMetricResult,
    RunEvaluator,
    normalize_key,
)


# ============================================================================
# 1. Identifier Parsing Tests
# ============================================================================

def test_parse_identifier_list_json_array() -> None:
    raw = '["phytochemical_name", "chembl_id", "imppat_id"]'
    parsed = parse_identifier_list(raw)
    assert parsed == ["phytochemical_name", "chembl_id", "imppat_id"]


def test_parse_identifier_list_single_string() -> None:
    raw = '["therapeutic_use"]'
    parsed = parse_identifier_list(raw)
    assert parsed == ["therapeutic_use"]


def test_parse_identifier_list_native_list() -> None:
    raw = ["alias", "normalized_alias"]
    parsed = parse_identifier_list(raw)
    assert parsed == ["alias", "normalized_alias"]


def test_parse_identifier_list_comma_separated() -> None:
    raw = "standard_value, standard_relation, standard_units"
    parsed = parse_identifier_list(raw)
    assert parsed == ["standard_value", "standard_relation", "standard_units"]


def test_parse_identifier_list_empty_or_none() -> None:
    assert parse_identifier_list("") == []
    assert parse_identifier_list("[]") == []
    assert parse_identifier_list(None) == []


# ============================================================================
# 2. Text Normalization and Case-Key Construction Tests
# ============================================================================

def test_normalize_text_unicode_quotes() -> None:
    raw = "Does this plant’s recorded phytochemical have a “ChEMBL ID”?"
    normalized = normalize_text(raw)
    assert normalized == "Does this plant's recorded phytochemical have a \"ChEMBL ID\"?"


def test_slugify() -> None:
    assert slugify("Basella alba") == "basella_alba"
    assert slugify("Alpinia galanga (L.)") == "alpinia_galanga_l"
    assert slugify("  Ocimum   tenuiflorum  ") == "ocimum_tenuiflorum"


def test_normalize_key() -> None:
    assert normalize_key("InChI_Key") == "inchikey"
    assert normalize_key("mesh-id") == "meshid"
    assert normalize_key(" Plant  Part ") == "plantpart"
    assert normalize_key(None) == ""


# ============================================================================
# 3. Ground-Truth Status Assignment Tests
# ============================================================================

def test_status_assignment_no_evidence() -> None:
    case = GroundTruthCase(
        test_case_id="TC_test_01",
        plant_name="Test Plant",
        question_id="Q06",
        question="What health uses are associated with the leaves?",
        identifier=["plant_part", "therapeutic_use"],
        expected_facts=[],
        ground_truth_status="NO_MATCHING_GRAPH_EVIDENCE",
    )
    assert case.ground_truth_status == "NO_MATCHING_GRAPH_EVIDENCE"
    assert len(case.expected_facts) == 0


def test_status_assignment_verified() -> None:
    case = GroundTruthCase(
        test_case_id="TC_test_02",
        plant_name="Test Plant",
        question_id="Q01",
        question="Which compounds?",
        identifier=["phytochemical_name"],
        expected_facts=[
            {"expected_fact": "Limonene", "record": {"phytochemical_name": "Limonene"}}
        ],
        ground_truth_status="VERIFIED",
    )
    assert case.ground_truth_status == "VERIFIED"
    assert len(case.expected_facts) == 1


# ============================================================================
# 4. Metric Denominator and Division Handling Tests
# ============================================================================

def test_graph_precision_zero_retrieved_facts_returns_na() -> None:
    evaluator = RunEvaluator(ground_truth_cases={})
    eval_record = {
        "traces": {"tool_calling": []},  # No tools called, 0 retrieved facts
        "response": "No information found.",
    }
    gt_case = {
        "test_case_id": "TC_empty_01",
        "plant_name": "Test Plant",
        "question_id": "Q01",
        "question": "Which compounds?",
        "ground_truth_status": "NO_MATCHING_GRAPH_EVIDENCE",
        "expected_facts": [],
    }

    metric_res, _ = evaluator.evaluate_case(eval_record, gt_case)
    assert metric_res.retrieved_fact_count == 0
    assert metric_res.graph_precision == "N/A"


def test_graph_precision_valid_calculation() -> None:
    evaluator = RunEvaluator(ground_truth_cases={})
    eval_record = {
        "traces": {
            "tool_calling": [
                {
                    "tool_name": "retrieve_plant_graph",
                    "arguments": {"query_type": "GET_PHYTOCHEMICALS"},
                    "result": {
                        "facts": [
                            {"record": {"phytochemical_name": "Limonene", "inchi_key": "KEY1"}},
                            {"record": {"phytochemical_name": "UnknownCompound", "inchi_key": "KEY2"}},
                        ]
                    },
                }
            ]
        },
        "response": "* Limonene [1]",
    }
    gt_case = {
        "test_case_id": "TC_valid_01",
        "plant_name": "Test Plant",
        "question_id": "Q01",
        "question": "Which compounds?",
        "ground_truth_status": "VERIFIED",
        "expected_facts": [
            {"expected_fact": "Limonene", "record": {"phytochemical_name": "Limonene", "inchi_key": "KEY1"}}
        ],
    }

    metric_res, _ = evaluator.evaluate_case(eval_record, gt_case)
    assert metric_res.retrieved_fact_count == 2
    assert metric_res.relevant_retrieved_fact_count == 1
    assert metric_res.graph_precision == 0.5


def test_groundedness_and_traceability_zero_claims_returns_na() -> None:
    evaluator = RunEvaluator(ground_truth_cases={})
    eval_record = {
        "traces": {"tool_calling": []},
        "response": "For learning only; this is not medical advice.",  # Disclaimer filtered out
    }
    gt_case = {
        "test_case_id": "TC_disclaimer_01",
        "plant_name": "Test Plant",
        "question_id": "Q01",
        "question": "Which compounds?",
        "ground_truth_status": "VERIFIED",
        "expected_facts": [],
    }

    metric_res, _ = evaluator.evaluate_case(eval_record, gt_case)
    assert metric_res.factual_claim_count == 0
    assert metric_res.groundedness == "N/A"
    assert metric_res.traceability == "N/A"


# ============================================================================
# 5. Scope Enforcement: Leaf Question Specificity
# ============================================================================

def test_leaf_scope_enforcement_general_facts_not_relevant() -> None:
    evaluator = RunEvaluator(ground_truth_cases={})
    # Agent called general GET_THERAPEUTIC_USES with no leaf scope, returning bark use
    eval_record = {
        "traces": {
            "tool_calling": [
                {
                    "tool_name": "retrieve_plant_graph",
                    "arguments": {"query_type": "GET_THERAPEUTIC_USES"},  # No part_id specified
                    "result": {
                        "facts": [
                            {"record": {"therapeutic_use": "Antihypertensive agents", "mesh_id": "D000959"}},
                        ]
                    },
                }
            ]
        },
        "response": "* Bark: Antihypertensive agents [1]",
    }
    gt_case = {
        "test_case_id": "TC_basella_Q06",
        "plant_name": "Basella alba",
        "question_id": "Q06",
        "question": "What health uses are associated with the leaves of this plant?",
        "ground_truth_status": "VERIFIED",
        "expected_facts": [
            {"expected_fact": "leaf: Diuretics", "record": {"plant_part": "leaf", "therapeutic_use": "Diuretics"}}
        ],
    }

    metric_res, _ = evaluator.evaluate_case(eval_record, gt_case)
    assert metric_res.retrieved_fact_count == 1
    # Antihypertensive agents is bark only, NOT leaf, and retrieved by general query
    assert metric_res.relevant_retrieved_fact_count == 0
    assert metric_res.graph_precision == 0.0
    assert "Leaf scope violation" in metric_res.review_notes


# ============================================================================
# 6. Trace Completeness Tests
# ============================================================================

def test_trace_completeness_perfect_score() -> None:
    evaluator = RunEvaluator(ground_truth_cases={})
    eval_record = {
        "traces": {
            "timeline": [
                {"event_type": "app_session_created"},
                {"event_type": "app_turn_started"},
            ],
            "tool_calling": [
                {"tool_name": "retrieve_plant_graph", "status": "ok"}
            ],
        },
        "response": "Here is the verified answer.",
    }
    score = evaluator._compute_trace_completeness(eval_record, retrieved_count=1)
    assert score == 1.0


def test_trace_completeness_partial_score() -> None:
    evaluator = RunEvaluator(ground_truth_cases={})
    # Missing session_created and tool call failed
    eval_record = {
        "traces": {
            "timeline": [
                {"event_type": "app_turn_started"},
            ],
            "tool_calling": [
                {"tool_name": "retrieve_plant_graph", "status": "error"}
            ],
        },
        "response": "Fallback answer.",
    }
    score = evaluator._compute_trace_completeness(eval_record, retrieved_count=0)
    assert 0.0 < score < 1.0
