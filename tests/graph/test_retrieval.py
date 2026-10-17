import json
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.agents.graph.agent import GraphAgent
from backend.agents.graph.retrieval import QUERIES, PlantGraphRetrieval
from backend.contracts.actions import Action, ActionName, AgentInvocation, Capability
from backend.contracts.agents import GraphAgentInput, GraphParameters, GraphQuery, QueryType
from backend.contracts.base import CorrelationMetadata
from backend.database.neo4j.errors import GraphDatabaseError


def request(kind=QueryType.GET_PHYTOCHEMICALS, **parameters):
    return GraphAgentInput(
        invocation=AgentInvocation(
            correlation=CorrelationMetadata(session_id=uuid4()),
            action=Action(name=ActionName.RETRIEVE_GRAPH),
            capability=Capability.GRAPH,
        ),
        query=GraphQuery(
            query_type=kind,
            parameters=GraphParameters(
                plant_id=parameters.pop("plant_id", str(uuid4())), **parameters
            ),
        ),
        objective_ids=[uuid4()],
    )


def row(name="compound", value="A"):
    return {
        "fact": {"inchi_key": value, "phytochemical_name": name},
        "nodes": [
            {"plant_name": "Synthetic plant"},
            {"plant_part_id": "part1"},
            {
                "inchi_key": value,
                "phytochemical_name": name,
                "source_url": "https://example.org/synthetic",
            },
        ],
        "relations": ["HAS_PART", "CONTAINS"],
    }


def repository(rows):
    graph, pg = AsyncMock(), AsyncMock()
    pg.scalar.return_value = "Synthetic plant"
    graph.read.return_value = rows
    return PlantGraphRetrieval(graph, pg)


@pytest.mark.parametrize("kind", list(QUERIES))
async def test_every_allowed_query_is_anchored_bounded_and_parameterized(kind):
    params = {}
    required = {
        QueryType.GET_PLANT_PART_DETAILS: "part_id",
        QueryType.GET_PHYTOCHEMICAL_DETAILS: "compound_id",
        QueryType.GET_PLANTS_CONTAINING_COMPOUND: "compound_id",
        QueryType.GET_PLANTS_FOR_THERAPEUTIC_USE: "therapeutic_use_id",
        QueryType.GET_COMPOUNDS_TARGETING_PROTEIN: "target_id",
    }
    if kind in required:
        params[required[kind]] = "fixture:identifier"
    req = request(kind, **params)
    repo = repository([row()])
    result = await repo.retrieve(req)
    assert result.evidence and result.completed_objectives == req.objective_ids
    query, parameters = repo.graph.read.call_args.args
    assert "{plant_name:$name}" in query and "LIMIT $limit" in query
    assert "DELETE" not in query
    assert parameters["limit"] == req.query.limit + 1
    assert repo.graph.read.call_args.kwargs["timeout_seconds"] == req.query.timeout_seconds


async def test_stable_citations_full_provenance_and_conservative_evidence_class():
    repo, req = repository([row()]), request()
    first, second = await repo.retrieve(req), await repo.retrieve(req)
    assert first.evidence[0].evidence_id == second.evidence[0].evidence_id
    evidence = first.evidence[0]
    assert evidence.evidence_type == "unknown"
    assert evidence.source_quality == 0
    assert evidence.graph_links == [(0, "HAS_PART", 1), (1, "CONTAINS", 2)]
    assert evidence.source_urls == []  # A compound URL is not a document citation.
    assert json.loads(evidence.claim)["inchi_key"] == "A"
    assert evidence.graph_nodes[-1]["inchi_key"] == "A"


async def test_only_traversed_document_url_is_exposed_as_external_source():
    value = row()
    value["nodes"].extend(
        [
            {"document_chembl_id": "doc1", "document_url": "https://example.org/paper"},
            {"uniprot_id": "target1", "source_url": "https://example.org/target"},
        ]
    )
    value["relations"].extend(["REPORTED_IN", "MEASURED_ON"])
    result = await repository([value]).retrieve(request(QueryType.GET_EVIDENCE))
    assert result.evidence[0].source_urls == ["https://example.org/paper"]


async def test_document_chembl_id_links_to_exact_record_when_url_is_absent():
    value = row()
    value["nodes"].append({"document_chembl_id": "CHEMBL1156867"})
    value["relations"].append("REPORTED_IN")
    result = await repository([value]).retrieve(request(QueryType.GET_EVIDENCE))
    assert result.evidence[0].source_urls == [
        "https://www.ebi.ac.uk/chembl/id_lookup/CHEMBL1156867"
    ]


async def test_limits_are_disclosed_and_never_silent_string_truncation():
    req = request()
    req.query.limit = 1
    result = await repository([row(), row("second", "B")]).retrieve(req)
    assert result.truncated and len(result.evidence) == 1
    assert "more records" in result.limitations[0]
    result = await repository([row("x" * 5000)]).retrieve(request())
    assert not result.evidence and result.gaps and not result.gaps[0].recoverable


async def test_empty_result_is_terminal_gap_not_negative_evidence():
    result = await repository([]).retrieve(request())
    assert not result.completed_objectives and not result.evidence
    assert not result.gaps[0].recoverable
    assert "does not disprove" in result.gaps[0].description


async def test_scope_rejection_never_queries_database():
    repo = repository([])
    result = await repo.retrieve(request(QueryType.COMPARE_PLANTS, comparison_plant_id="other"))
    assert result.gaps
    result = await repo.retrieve(request(plant_id="invalid"))
    assert result.gaps
    repo.graph.read.assert_not_awaited()
    repo.postgres.scalar.assert_not_awaited()


async def test_invalid_filter_is_not_silently_ignored():
    repo = repository([])
    result = await repo.retrieve(request(QueryType.GET_PLANT_DETAILS, compound_id="compound"))
    assert "not valid" in result.gaps[0].description
    repo.graph.read.assert_not_awaited()


async def test_trace_is_bound_to_history_and_same_plant():
    repo, req = repository([row()]), request()
    evidence = (await repo.retrieve(req)).evidence[0]
    trace = request(
        QueryType.TRACE_EVIDENCE,
        plant_id=req.query.parameters.plant_id,
        evidence_id=str(evidence.evidence_id),
    )
    trace.prior_evidence = [evidence]
    result = await repo.retrieve(trace)
    assert result.evidence[0] == evidence and result.evidence[0] is not evidence
    trace.query.parameters.plant_id = str(uuid4())
    assert (await repo.retrieve(trace)).gaps
    assert repo.graph.read.await_count == 1


async def test_conflicting_properties_are_data_conflicts_not_identity_or_clinical_claims():
    result = await repository([row("first"), row("second")]).retrieve(request())
    assert len(result.contradictions) == 1
    assert not result.contradictions[0].affects_identity
    assert len(result.contradictions[0].evidence_refs) == 2
    assert all(e.evidence_type == "unknown" for e in result.evidence)


async def test_optional_document_and_target_branches_keep_actual_endpoints():
    value = deepcopy(row())
    value["fact"] = {"bioactivity_id": "activity1", "high_confidence_tier": "high"}
    value["nodes"] += [value["fact"], {"document_chembl_id": "doc1"}, {"uniprot_id": "target1"}]
    value["relations"] += ["HAS_BIOACTIVITY", "REPORTED_IN", "MEASURED_ON"]
    result = await repository([value]).retrieve(request(QueryType.GET_EVIDENCE))
    assert result.evidence[0].graph_links[-2:] == [(3, "REPORTED_IN", 4), (3, "MEASURED_ON", 5)]
    value["nodes"].pop(4)
    value["relations"].remove("REPORTED_IN")
    result = await repository([value]).retrieve(request(QueryType.GET_EVIDENCE))
    assert "no linked document" in result.limitations[0]
    assert result.evidence[0].evidence_type == "unknown"


async def test_bioactivity_retrieval_includes_recorded_assay_target():
    req = request(QueryType.GET_BIOACTIVITY, compound_id="fixture:compound")
    repo = repository([row()])
    await repo.retrieve(req)
    query, parameters = repo.graph.read.call_args.args
    assert "OPTIONAL MATCH (activity)-[:MEASURED_ON]->(target:Protein_Target)" in query
    assert "properties(target)" in query
    assert parameters["compound"] == "fixture:compound"


@pytest.mark.parametrize(
    "code,retryable,expected",
    [
        ("TIMEOUT", True, "timeout"),
        ("UNAVAILABLE", True, "dependency_unavailable"),
        ("AUTHENTICATION", False, "permanent"),
        ("QUERY_FAILED", False, "permanent"),
    ],
)
async def test_errors_preserve_retry_policy_without_leaking_details(code, retryable, expected):
    repo = repository([])
    repo.graph.read.side_effect = GraphDatabaseError(
        code, "secret credentials", retryable=retryable
    )
    result = await GraphAgent(repo).execute(request())
    assert result.error_type == expected and result.retryable == retryable
    assert "secret" not in result.model_dump_json()


async def test_mutated_request_is_revalidated():
    req = request()
    object.__setattr__(req.query, "limit", 100000)
    result = await GraphAgent(repository([])).execute(req)
    assert result.error_type == "invalid_input"
