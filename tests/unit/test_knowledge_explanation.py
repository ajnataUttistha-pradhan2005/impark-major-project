import json

import pytest

from backend.contracts.agents import CandidatePlant
from backend.contracts.evidence import Evidence, Provenance
from backend.contracts.response import FinalResponseRequest, ResponseContext
from backend.llm.guarded import GuardedResponseProvider
from backend.llm.knowledge_explanation import explanation_packet, validate_explanations
from backend.llm.verbalize import answer_facts


def explanation_request() -> FinalResponseRequest:
    return FinalResponseRequest(
        response_context=ResponseContext(
            intent="GET_PHYTOCHEMICALS",
            answer_style="explanation",
            user_question="Explain each of them",
            resolved_plant=CandidatePlant(
                plant_id="fixture:plant", label="Basella alba", confidence=1
            ),
            graph_evidence=[
                Evidence(
                    modality="graph",
                    claim=json.dumps({
                        "phytochemical_name": "Kaempferol",
                        "classyfire_class": "Flavonoids",
                    }),
                    graph_nodes=[{"plant_part": "leaf"}],
                    confidence=1,
                    provenance=Provenance(
                        source_id="fixture:plant", source_type="neo4j",
                        reference="GET_PHYTOCHEMICALS:fixture",
                    ),
                )
            ],
            outcome="Objectives satisfied",
        )
    )


class Model:
    name = "fixture:model"
    provider_name = "fixture"

    def __init__(self, result: str) -> None:
        self.result = result

    async def tokens(self, prompt, schema):
        assert "GENERAL scientific background" in prompt
        assert "Kaempferol" in prompt and "explanations" in schema["properties"]
        yield self.result


def test_explanation_packet_and_general_background_boundary() -> None:
    context = explanation_request().response_context
    facts = answer_facts(context)
    prompt, _ = explanation_packet(context, facts)
    assert '"plant": "Basella alba"' in prompt
    valid = json.dumps({"explanations": [{"id": "f1", "text": (
        "A flavonoid is a family of plant chemicals grouped by aspects of "
        "their chemical structure."
    )}]})
    assert validate_explanations(valid, context, facts)[0].fact_index == 0
    mixed = json.dumps({"explanations": [{"id": "f1", "text": (
        "A flavonoid is a family of plant chemicals grouped by structure. "
        "This compound cures disease."
    )}]})
    assert validate_explanations(mixed, context, facts)[0].text == (
        "A flavonoid is a family of plant chemicals grouped by structure."
    )
    for unsafe in (
        "Basella alba contains enough of this compound to help people.",
        "Kaempferol cures cough in clinical studies.",
        "Kaempferol inhibits a protein at 20 nM.",
        "Research at Oxford proves the result.",
        "See https://example.com for proof.",
    ):
        with pytest.raises(ValueError):
            validate_explanations(
                json.dumps({"explanations": [{"id": "f1", "text": unsafe}]}),
                context,
                facts,
            )


async def test_model_background_is_separate_from_cited_graph_fact() -> None:
    request = explanation_request()
    result = await GuardedResponseProvider(Model(json.dumps({"explanations": [{"id": "f1", "text": (
        "A flavonoid is a family of plant chemicals grouped by aspects of "
        "their chemical structure."
    )}]}))).generate(request)
    assert "Kaempferol is listed" in result.text
    assert "[1]" in result.text
    assert "general model knowledge" in result.text
    assert "**In general:**" in result.text
    assert result.citation_ids == [request.response_context.graph_evidence[0].evidence_id]
    assert not result.fallback_used


async def test_unsafe_background_falls_back_to_grounded_answer() -> None:
    request = explanation_request()
    result = await GuardedResponseProvider(Model(json.dumps({"explanations": [{"id": "f1", "text": (
        "Basella alba treats disease because Kaempferol inhibits a protein."
    )}]}))).generate(request)
    assert result.fallback_used
    assert "treats disease" not in result.text
    assert result.citation_ids == [request.response_context.graph_evidence[0].evidence_id]
