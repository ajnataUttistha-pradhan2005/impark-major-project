import json

import pytest

from backend.contracts.agents import CandidatePlant
from backend.contracts.evidence import Evidence, Provenance
from backend.contracts.response import ResponseContext
from backend.llm.concise import concise_answer
from backend.llm.narrative import packet, validate_narrative
from backend.llm.verbalize import answer_facts


def context() -> ResponseContext:
    return ResponseContext(
        intent="GET_THERAPEUTIC_USES",
        user_question="What are its uses?",
        resolved_plant=CandidatePlant(
            plant_id="fixture:plant", label="Plectranthus amboinicus", confidence=1
        ),
        graph_evidence=[
            Evidence(
                modality="graph",
                claim=json.dumps({"therapeutic_use": term, "mesh_category_name": "Diseases"}),
                graph_nodes=[{"plant_part": "leaf"}],
                graph_links=[(0, "HAS_PART", 1), (1, "USED_FOR", 2)],
                confidence=1,
                provenance=Provenance(
                    source_id=f"fixture:{index}",
                    source_type="neo4j",
                    reference="GET_THERAPEUTIC_USES:fixture",
                ),
            )
            for index, term in enumerate(("Bronchitis", "Cough"))
        ],
        outcome="Objectives satisfied",
    )


def encoded(text: str, ids: list[str] | None = None) -> str:
    return json.dumps({"paragraphs": [{"text": text, "ids": ids or ["f1", "f2"]}]})


def test_packet_contains_meanings_and_no_database_client() -> None:
    ctx = context()
    prompt, schema = packet(ctx, answer_facts(ctx))
    assert "A plant part is associated with a use term" in prompt
    assert "Bronchitis" in prompt
    assert "password" not in prompt
    assert "sentences" in schema["properties"]


def test_each_generated_sentence_must_cite_its_own_supported_fact() -> None:
    ctx = context()
    facts = answer_facts(ctx)
    valid = json.dumps(
        {
            "sentences": [
                {
                    "text": "The leaf of Plectranthus amboinicus is linked with Bronchitis.",
                    "ids": ["f1"],
                },
                {"text": "The same plant part is associated with Cough.", "ids": ["f2"]},
            ]
        }
    )
    assert [block.citations for block in validate_narrative(valid, ctx, facts)] == [
        [ctx.graph_evidence[0].evidence_id],
        [ctx.graph_evidence[1].evidence_id],
    ]
    unsupported = valid.replace("Cough", "Malaria")
    with pytest.raises(ValueError):
        validate_narrative(unsupported, ctx, facts)


def test_valid_explanation_retains_exact_evidence_ids() -> None:
    ctx = context()
    blocks = validate_narrative(
        encoded(
            "The leaf of Plectranthus amboinicus is linked with Bronchitis and Cough. "
            "These names describe conditions associated with that plant part."
        ),
        ctx,
        answer_facts(ctx),
    )
    assert blocks[0].citations == [item.evidence_id for item in ctx.graph_evidence]


def test_expand_compound_followup_gives_cited_itemized_explanation() -> None:
    ctx = context().model_copy(
        update={
            "intent": "GET_PHYTOCHEMICALS",
            "user_question": "Could you expand on that?",
            "answer_style": "explanation",
            "graph_evidence": [
                Evidence(
                    modality="graph",
                    claim=json.dumps(
                        {"phytochemical_name": name, "classyfire_class": "Flavonoids"}
                    ),
                    graph_nodes=[{"plant_part": "leaf"}],
                    graph_links=[(0, "HAS_PART", 1), (1, "CONTAINS", 2)],
                    confidence=1,
                    provenance=Provenance(
                        source_id=f"fixture:{index}",
                        source_type="neo4j",
                        reference="GET_PHYTOCHEMICALS:fixture",
                    ),
                )
                for index, name in enumerate(("Quercetin", "Kaempferol"))
            ],
        }
    )
    answer = concise_answer(ctx, answer_facts(ctx))
    assert answer is not None
    assert "**Quercetin**" in answer.text and "**Kaempferol**" in answer.text
    assert "classified as Flavonoids" in answer.text
    assert answer.citation_ids == [item.evidence_id for item in ctx.graph_evidence]


def test_plain_language_part_summary_keeps_cited_parts_and_rejects_new_one() -> None:
    ctx = context()
    ctx.intent = "GET_PLANT_PARTS"
    ctx.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps({"plant_part": part}),
            graph_nodes=[{"plant_part": part}],
            graph_links=[(0, "HAS_PART", 1)],
            confidence=1,
            provenance=Provenance(
                source_id=f"fixture:{part}",
                source_type="neo4j",
                reference="GET_PLANT_PARTS:fixture",
            ),
        )
        for part in ("leaf", "root", "fruit")
    ]
    draft = json.dumps(
        {
            "sentences": [
                {
                    "text": "Plectranthus amboinicus has several named parts that belong to it.",
                    "ids": ["f1", "f2", "f3"],
                },
                {
                    "text": "These parts include leaf, root, and fruit.",
                    "ids": ["f1", "f2", "f3"],
                },
            ]
        }
    )
    assert len(validate_narrative(draft, ctx, answer_facts(ctx))) == 2
    with pytest.raises(ValueError):
        validate_narrative(draft.replace("fruit", "seed"), ctx, answer_facts(ctx))


@pytest.mark.parametrize(
    "answer",
    [
        "Plectranthus amboinicus leaf helps relieve Bronchitis and Cough symptoms.",
        "Plectranthus amboinicus is traditionally used for Bronchitis and Cough.",
        "Plectranthus amboinicus leaf cures Bronchitis and Cough.",
        "Plectranthus amboinicus leaf is linked with Bronchitis and Malaria.",
        "Plectranthus amboinicus leaf is linked with Bronchitis in 2026.",
        "The graph database says Plectranthus amboinicus leaf treats Cough.",
        "The leaf is commonly observed in relation to Bronchitis and Cough.",
        "People used Plectranthus amboinicus leaf for Bronchitis and Cough.",
        "The leaf has a strong association with Bronchitis and Cough.",
        "The association between the leaf and Bronchitis is reported (f1).",
        "No specific uses or activities are recorded for Plectranthus amboinicus.",
        "Plectranthus amboinicus leaf is linked with Bronchitis and essential oils.",
    ],
)
def test_unsupported_benefits_entities_numbers_and_process_are_rejected(answer: str) -> None:
    ctx = context()
    with pytest.raises(ValueError):
        validate_narrative(encoded(answer), ctx, answer_facts(ctx))


def test_invalid_citation_mapping_is_rejected() -> None:
    ctx = context()
    with pytest.raises(ValueError):
        validate_narrative(
            encoded("The leaf of Plectranthus amboinicus is linked with Bronchitis.", ["f9"]),
            ctx,
            answer_facts(ctx),
        )


def test_rejected_model_has_explanatory_reported_use_fallback() -> None:
    ctx = context()
    result = concise_answer(ctx, answer_facts(ctx))
    assert result is not None
    assert "the leaf is linked with recorded topics" in result.text
    assert "Bronchitis [1]" in result.text and "Cough [2]" in result.text
    assert "treats it" in result.text
    assert "graph" not in result.text.casefold()
    assert result.citation_ids == [item.evidence_id for item in ctx.graph_evidence]


def test_bioactivity_fallback_explains_metrics_without_dumping_all_assays() -> None:
    ctx = context().model_copy(deep=True)
    ctx.intent = "GET_BIOACTIVITY"
    ctx.user_question = "Explain these bioactivity measurements"
    ctx.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps(
                {"standard_type": metric, "standard_value": value, "standard_units": "nM"}
            ),
            graph_nodes=[{"phytochemical_name": "Caryophyllene oxide"}, {"target_name": target}],
            confidence=1,
            provenance=Provenance(
                source_id=f"fixture:{index}",
                source_type="neo4j",
                reference="GET_BIOACTIVITY:fixture",
            ),
        )
        for index, (metric, value, target) in enumerate(
            [
                ("Kd", 20, "Interleukin-2"),
                ("Potency", 3981, "Alpha-galactosidase A"),
                ("Potency", 3981, "Huntingtin"),
            ]
        )
    ]
    result = concise_answer(ctx, answer_facts(ctx))
    assert result is not None
    assert "Bioactivity means" in result.text
    assert "Kd is a binding-related concentration" in result.text
    assert "Huntingtin" not in result.text
    assert "strong" not in result.text
    assert result.citation_ids == [item.evidence_id for item in ctx.graph_evidence[:2]]


def test_document_fallback_hides_placeholder_journal_fields() -> None:
    ctx = context().model_copy(deep=True)
    ctx.intent = "GET_DOCUMENTS"
    ctx.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps({"document_journal": "NA", "document_year": "NA", "source": "ChEMBL"}),
            confidence=1,
            provenance=Provenance(
                source_id="fixture:doc",
                source_type="neo4j",
                reference="GET_DOCUMENTS:fixture",
            ),
        )
    ]
    result = concise_answer(ctx, answer_facts(ctx))
    assert result is not None
    assert "ChEMBL source entry" in result.text
    assert "NA" not in result.text
