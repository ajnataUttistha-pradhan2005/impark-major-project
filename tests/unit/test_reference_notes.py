import json

import httpx
import pytest

from backend.agents.text.interpretation import scoped_queries
from backend.contracts.agents import CandidatePlant, QueryType, ResolvedMention
from backend.contracts.evidence import Evidence, Provenance
from backend.contracts.response import ResponseContext
from backend.evidence.context_builder import rank_graph_evidence
from backend.evidence.reference import ReferenceNotes
from backend.evidence.reference_import import fetch_mesh_note
from backend.llm.narrative import reference_facts
from backend.llm.verbalize import answer_facts


class FakeDatabase:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def read(self, sql, ids):
        assert "external_id=ANY($1::text[])" in sql
        self.calls += 1
        return [row for row in self.rows if row["external_id"] in ids]


def context(mesh_id="D015746"):
    return ResponseContext(
        intent="GET_THERAPEUTIC_USES",
        user_question="What is abdominal pain?",
        graph_evidence=[
            Evidence(
                modality="graph",
                confidence=1,
                claim=json.dumps(
                    {"therapeutic_use": "Abdominal Pain", "mesh_category_name": "Diseases"}
                ),
                graph_nodes=[
                    {"plant_part": "leaf"},
                    {"mesh_id": mesh_id, "therapeutic_use": "Abdominal Pain"},
                ],
                provenance=Provenance(
                    source_id="plant:1",
                    source_type="neo4j",
                    reference="GET_THERAPEUTIC_USES:fixture",
                ),
            )
        ],
        outcome="Objectives satisfied",
    )


@pytest.mark.asyncio
async def test_reference_note_requires_matching_graph_id_and_label():
    row = {
        "external_id": "D015746",
        "label": "Abdominal Pain",
        "description": "Sensation of discomfort in the abdominal region.",
        "source_url": "https://id.nlm.nih.gov/mesh/D015746.json",
    }
    db = FakeDatabase([row])
    ctx = context()
    notes = await ReferenceNotes(db).for_context(ctx)
    assert len(notes) == 1
    ctx.text_evidence = notes
    assert reference_facts(ctx, answer_facts(ctx))[0].citation_id == notes[0].evidence_id
    assert await ReferenceNotes(db).for_context(context("D000000")) == []
    assert (
        await ReferenceNotes(FakeDatabase([{**row, "label": "Wrong term"}])).for_context(ctx) == []
    )
    ctx.user_question = "What are its uses?"
    assert reference_facts(ctx, answer_facts(ctx)) == []


def test_named_use_explanation_stays_within_locked_plant():
    queries = scoped_queries(
        "What is Abdominal Pain?",
        [CandidatePlant(plant_id="plant:1", label="Plectranthus amboinicus", confidence=1)],
        [
            ResolvedMention(
                entity_id="D015746", kind="therapeutic_use", label="Abdominal Pain", confidence=1
            )
        ],
        [QueryType.GET_PLANT_DETAILS],
        None,
    )
    assert queries[0].query_type == QueryType.GET_THERAPEUTIC_USES
    assert queries[0].parameters.plant_id == "plant:1"
    assert queries[0].parameters.therapeutic_use_id == "D015746"


def test_named_target_measurement_routes_to_bounded_assay_evidence():
    queries = scoped_queries(
        "What bioactivity measurements involve Interleukin-2?",
        [CandidatePlant(plant_id="plant:1", label="Plectranthus amboinicus", confidence=1)],
        [ResolvedMention(entity_id="P60568", kind="target", label="Interleukin-2", confidence=1)],
        [QueryType.GET_BIOACTIVITY],
        None,
    )
    assert queries[0].query_type == QueryType.GET_EVIDENCE
    assert queries[0].parameters.target_id == "P60568"


def test_context_ranking_prefers_named_term_without_changing_evidence_state():
    first = context().graph_evidence[0]
    second = first.model_copy(deep=True)
    second.graph_nodes[1]["therapeutic_use"] = "Bronchitis"
    original = [first, second]
    ranked = rank_graph_evidence(original, "What is bronchitis?", "Plectranthus amboinicus")
    assert ranked == [second, first]
    assert original == [first, second]


@pytest.mark.asyncio
async def test_mesh_import_checks_identifier_label_and_concept():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("D015746.json"):
            return httpx.Response(
                200,
                json={
                    "identifier": "D015746",
                    "label": {"@language": "en", "@value": "Abdominal Pain"},
                    "preferredConcept": "http://id.nlm.nih.gov/mesh/M0024135",
                },
            )
        return httpx.Response(
            200,
            json={
                "@id": "http://id.nlm.nih.gov/mesh/M0024135",
                "label": {"@language": "en", "@value": "Abdominal Pain"},
                "scopeNote": {
                    "@language": "en",
                    "@value": "Sensation of discomfort in the abdominal region.",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_mesh_note(client, "D015746", "Abdominal Pain") == (
            "Abdominal Pain",
            "Sensation of discomfort in the abdominal region.",
            "https://id.nlm.nih.gov/mesh/D015746.json",
        )
        assert await fetch_mesh_note(client, "D015746", "Another term") is None
        assert await fetch_mesh_note(client, "../bad", "Abdominal Pain") is None
