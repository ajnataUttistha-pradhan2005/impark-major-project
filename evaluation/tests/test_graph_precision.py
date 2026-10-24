"""Tests for graph retrieval precision and canonical entity extraction."""

from uuid import uuid4

from evaluation.canonical_extractor import extract_canonical_node, extract_evaluation_turn
from evaluation.metrics.graph_precision import calculate_graph_precision
from evaluation.models import CanonicalNodeKey, GraphEntityType


def test_extract_every_supported_business_key_type():
    """Verify that every supported business key type is extracted to the correct canonical key."""
    cases = [
        ({"inchi_key": "INCHI_ABC"}, GraphEntityType.COMPOUND, "INCHI_ABC"),
        ({"uniprot_id": "P12345"}, GraphEntityType.PROTEIN_TARGET, "P12345"),
        ({"plant_part_id": "part:bark"}, GraphEntityType.PLANT_PART, "part:bark"),
        ({"bioactivity_id": "ACT_999"}, GraphEntityType.BIOACTIVITY, "ACT_999"),
        ({"document_chembl_id": "CHEMBL555"}, GraphEntityType.DOCUMENT, "CHEMBL555"),
        ({"mesh_id": "D001234"}, GraphEntityType.THERAPEUTIC_USE, "D001234"),
        ({"plant_name": "Ocimum sanctum"}, GraphEntityType.PLANT, "Ocimum sanctum"),
        ({"plant_id": "plant:tulsi"}, GraphEntityType.PLANT, "plant:tulsi"),
        ({"normalized_alias": "Holy Basil"}, GraphEntityType.PLANT_ALIAS, "holy basil"),
        # Fallback names
        ({"phytochemical_name": "Eugenol"}, GraphEntityType.COMPOUND, "Eugenol"),
        ({"compound_name": "Curcumin"}, GraphEntityType.COMPOUND, "Curcumin"),
        ({"plant_part": "leaf"}, GraphEntityType.PLANT_PART, "leaf"),
        ({"target_name": "COX-2"}, GraphEntityType.PROTEIN_TARGET, "COX-2"),
        ({"therapeutic_use": "Fever"}, GraphEntityType.THERAPEUTIC_USE, "Fever"),
    ]

    for node_dict, expected_type, expected_id in cases:
        key, diag = extract_canonical_node(node_dict)
        assert diag is None, f"Unexpected diagnostic for {node_dict}"
        assert key is not None
        assert key.entity_type == expected_type
        assert key.business_id == expected_id


def test_missing_and_unrecognized_business_keys():
    """Verify that empty and unrecognized nodes produce proper diagnostics."""
    empty_key, empty_diag = extract_canonical_node({})
    assert empty_key is None
    assert empty_diag is not None
    assert empty_diag.code == "EMPTY_NODE"

    unrec_key, unrec_diag = extract_canonical_node({"random_property": "some_value"})
    assert unrec_key is None
    assert unrec_diag is not None
    assert unrec_diag.code == "UNRECOGNIZED_NODE"


def test_deduplication_of_nodes_across_multiple_evidence_records():
    """Verify duplicate nodes across distinct evidence records are deduplicated."""
    state = {
        "evidence": {
            "graph": [
                {
                    "graph_nodes": [
                        {"inchi_key": "INCHI_REPEAT"},
                        {"plant_part_id": "leaf"},
                    ]
                },
                {
                    "graph_nodes": [
                        {"inchi_key": "INCHI_REPEAT"},  # duplicate
                        {"inchi_key": "INCHI_NEW"},
                    ]
                },
            ]
        }
    }
    turn = extract_evaluation_turn(run_id=uuid4(), session_id=uuid4(), state=state)

    assert len(turn.retrieved_graph_nodes) == 3
    keys = {n.business_id for n in turn.retrieved_graph_nodes}
    assert keys == {"INCHI_REPEAT", "leaf", "INCHI_NEW"}


def test_nonempty_graph_retrieval_precision():
    """Verify calculation of precision when retrieved set is nonempty."""
    retrieved = {
        CanonicalNodeKey(entity_type=GraphEntityType.COMPOUND, business_id="C1"),
        CanonicalNodeKey(entity_type=GraphEntityType.COMPOUND, business_id="C2"),
        CanonicalNodeKey(entity_type=GraphEntityType.COMPOUND, business_id="C3"),
        CanonicalNodeKey(entity_type=GraphEntityType.COMPOUND, business_id="C4"),
    }
    relevant = {
        CanonicalNodeKey(entity_type=GraphEntityType.COMPOUND, business_id="C1"),
        CanonicalNodeKey(entity_type=GraphEntityType.COMPOUND, business_id="C2"),
        CanonicalNodeKey(entity_type=GraphEntityType.COMPOUND, business_id="OTHER"),
    }

    precision, diags = calculate_graph_precision(retrieved, relevant)
    assert precision == 0.5  # 2 matched / 4 retrieved
    assert len(diags) == 0


def test_both_empty_convention_returns_one():
    """Verify documented convention: both empty sets return 1.0 with diagnostic."""
    precision, diags = calculate_graph_precision(set(), set())
    assert precision == 1.0
    assert len(diags) == 1
    assert diags[0].code == "EMPTY_EMPTY_PRECISION"


def test_zero_retrieval_when_relevant_expected_returns_none():
    """Verify zero retrieval when relevant nodes were expected returns None with diagnostic."""
    relevant = {CanonicalNodeKey(entity_type=GraphEntityType.COMPOUND, business_id="C1")}
    precision, diags = calculate_graph_precision(set(), relevant)

    assert precision is None
    assert len(diags) == 1
    assert diags[0].code == "ZERO_RETRIEVAL"
    assert diags[0].details["relevant_count"] == 1
