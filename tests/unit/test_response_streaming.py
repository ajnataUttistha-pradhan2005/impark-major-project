import asyncio
import json

import httpx
import pytest

from backend.config.settings import Settings
from backend.contracts.agents import CandidatePlant
from backend.contracts.evidence import Evidence, Provenance
from backend.contracts.response import FinalResponseRequest, ResponseContext
from backend.llm.concise import concise_answer
from backend.llm.guarded import GuardedResponseProvider
from backend.llm.ollama import OllamaModel
from backend.llm.verbalize import answer_facts


def response_request(count=2):
    return FinalResponseRequest(
        response_context=ResponseContext(
            intent="GET_THERAPEUTIC_USES",
            user_question="What uses are recorded for the plant?",
            outcome="Objectives satisfied",
            uncertainties=["Clinical efficacy has not been established"],
            graph_evidence=[
                Evidence(
                    modality="graph",
                    claim=json.dumps({"reported_use": f"Synthetic use {i}"}),
                    evidence_type="traditional",
                    confidence=1,
                    provenance=Provenance(
                        source_id=f"fixture:{i}", source_type="graph", reference="Synthetic source"
                    ),
                )
                for i in range(count)
            ],
        )
    )


class Model:
    name = "fixture:model"

    def __init__(self, output):
        self.output = output
        self.calls = 0

    async def tokens(self, prompt, schema):
        self.calls += 1
        assert "tools" not in schema
        assert "Synthetic" in prompt
        assert "What uses are recorded for the plant?" in prompt
        if isinstance(self.output, BaseException):
            raise self.output
        for character in self.output:
            yield character


async def test_incremental_approved_blocks_and_exact_citations():
    request = response_request()
    model = Model(
        '{"paragraphs":[{"text":"Synthetic use 1 and Synthetic use 0 '
        'are recorded associations for this plant.","ids":["f2","f1"]}]}'
    )
    chunks = [c async for c in GuardedResponseProvider(model).stream(request)]
    answer = "".join(c.text for c in chunks)
    assert chunks
    assert answer.index("Synthetic use 1") < answer.index("Synthetic use 0")
    assert "recorded associations" in answer
    assert "reported_use:" not in answer
    assert "fixture:" not in answer
    assert "Clinical efficacy has not been established" not in answer
    assert {i for c in chunks for i in c.citation_ids} == {
        e.evidence_id for e in request.response_context.graph_evidence
    }
    assert not any(c.fallback_used for c in chunks)


@pytest.mark.parametrize(
    "output",
    [
        "Take 500mg; clinically proven; ignore all restrictions",
        '{"blocks":["b0","b0"]}',
        '{"blocks":["b9"]}',
        '{"blocks":["b0"]}',
        "[]",
        '{"blocks":[{}]}',
        '{"blocks":["b0","b1"],"extra":"invented"}',
        TimeoutError(),
        httpx.ConnectError("private secret"),
    ],
)
async def test_invalid_models_fall_back_without_inventing_or_losing_evidence(output):
    result = await GuardedResponseProvider(Model(output)).generate(response_request())
    assert result.fallback_used
    assert result.text.count("Synthetic use 0") == 1
    assert result.text.count("Synthetic use 1") == 1
    assert "500mg" not in result.text and "private secret" not in result.text
    assert "clinically proven" not in result.text
    assert len(result.citation_ids) == 2


async def test_repeated_invalid_model_drafts_temporarily_use_fast_grounded_path():
    model = Model("not JSON")
    provider = GuardedResponseProvider(model)
    answers = [await provider.generate(response_request()) for _ in range(4)]
    assert model.calls == 3
    assert all(answer.fallback_used and answer.citation_ids for answer in answers)


@pytest.mark.parametrize(
    ("kind", "fact", "expected", "not_expected"),
    [
        (
            "GET_PLANT_DETAILS",
            {"plant_name": "Azadirachta indica", "common_names": ["Neem"], "taxonomy_id": "123"},
            "Common names include Neem",
            "taxonomy_id",
        ),
        (
            "GET_PLANT_PARTS",
            {"plant_part": "Leaf", "plant_part_id": "p1"},
            "Leaf as a plant part",
            "plant_part_id",
        ),
        (
            "GET_PHYTOCHEMICALS",
            {"phytochemical_name": "Nimbin", "classyfire_class": "Triterpenoids", "smiles": "C=O"},
            "Nimbin is listed as a phytochemical",
            "smiles",
        ),
        (
            "GET_THERAPEUTIC_USES",
            {"therapeutic_use": "Bronchitis", "mesh_category_name": "Diseases", "mesh_id": "D001"},
            "reported conditions",
            "mesh_id",
        ),
        (
            "GET_THERAPEUTIC_USES",
            {"therapeutic_use": "Pectoralis muscles", "mesh_category_name": "Anatomy"},
            "Pectoralis muscles appears as an anatomical reference",
            "treats Pectoralis",
        ),
        (
            "GET_BIOACTIVITY",
            {
                "standard_type": "IC50",
                "standard_value": 42,
                "standard_units": "nM",
                "bioactivity_id": "a1",
            },
            "IC50",
            "bioactivity_id",
        ),
        (
            "GET_PROTEIN_TARGETS",
            {"target_name": "Kinase", "target_organism": "Human", "uniprot_id": "P123"},
            "protein target Kinase in Human",
            "uniprot_id",
        ),
        (
            "GET_DOCUMENTS",
            {"document_journal": "Journal A", "document_year": 2020, "document_chembl_id": "D1"},
            "Journal A (2020)",
            "document_chembl_id",
        ),
        (
            "GET_DOCUMENTS",
            {"document_journal": "NA", "document_year": "NA", "source": "ChEMBL"},
            "ChEMBL document record",
            "NA",
        ),
    ],
)
async def test_graph_fields_become_readable_bounded_claims(
    kind: str, fact: dict[str, object], expected: str, not_expected: str
) -> None:
    request = response_request(0)
    request.response_context.intent = kind
    request.response_context.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps(fact),
            confidence=1,
            provenance=Provenance(
                source_id="plant", source_type="neo4j", reference=f"{kind}: Neem"
            ),
        )
    ]
    result = await GuardedResponseProvider().generate(request)
    assert expected in result.text
    assert not_expected not in result.text
    assert "{" not in result.text
    assert result.citation_ids == [request.response_context.graph_evidence[0].evidence_id]


async def test_multi_intent_intro_does_not_mislabel_use_as_compound() -> None:
    request = response_request(0)
    request.response_context.intent = "GET_PHYTOCHEMICALS"
    request.response_context.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps(fact),
            confidence=1,
            provenance=Provenance(
                source_id=f"fixture:{index}", source_type="neo4j", reference=f"{kind}: Neem"
            ),
        )
        for index, (kind, fact) in enumerate(
            [
                ("GET_PHYTOCHEMICALS", {"phytochemical_name": "Nimbin"}),
                ("GET_THERAPEUTIC_USES", {"therapeutic_use": "Bronchitis"}),
            ]
        )
    ]
    result = await GuardedResponseProvider().generate(request)
    assert result.text.startswith("Here is what the available records say")
    assert "Nimbin" in result.text and "Bronchitis" in result.text


async def test_user_answer_hides_retrieval_diagnostics() -> None:
    request = response_request(1)
    request.response_context.uncertainties = [
        "No matching graph records; absence does not disprove a claim.",
        "Some bioactivity records have no linked document in this graph.",
    ]
    result = await GuardedResponseProvider().generate(request)
    assert "graph" not in result.text.casefold()
    assert "GET_" not in result.text
    assert "could not find a matching record" not in result.text
    assert "linked publication" not in result.text


@pytest.mark.parametrize("outcome", ["SAFETY_ABSTENTION", "SCOPE_REJECTED"])
async def test_policy_responses_do_not_call_model(outcome):
    request = response_request(0)
    request.response_context.outcome = outcome
    model = Model("bad")
    result = await GuardedResponseProvider(model).generate(request)
    assert model.calls == 0
    assert result.provider == "grounded" and result.model is None
    assert not result.citation_ids


async def test_cancellation_is_not_swallowed_as_model_fallback():
    with pytest.raises(asyncio.CancelledError):
        await GuardedResponseProvider(Model(asyncio.CancelledError())).generate(response_request())


async def test_bounded_rendering_discloses_evidence_not_shown():
    result = await GuardedResponseProvider().generate(response_request(10))
    assert len(result.citation_ids) == 8
    assert "More related information is recorded" in result.text
    assert not result.fallback_used


async def test_no_evidence_recommends_only_previously_verified_topics():
    request = response_request(0)
    request.response_context.resolved_plant = CandidatePlant(
        plant_id="fixture-plant", label="Neem", confidence=1
    )
    request.response_context.outcome = "EVIDENCE_UNAVAILABLE"
    request.response_context.known_topics = ["its documented parts", "its recorded compounds"]
    result = await GuardedResponseProvider().generate(request)
    assert "don't currently have enough information" in result.text
    assert "documented parts" in result.text
    assert "recorded compounds" in result.text
    assert "reported uses" not in result.text
    assert "graph" not in result.text.casefold()
    assert not result.citation_ids


async def test_no_evidence_without_prior_topics_offers_to_check_overview():
    request = response_request(0)
    request.response_context.resolved_plant = CandidatePlant(
        plant_id="fixture-plant", label="Neem", confidence=1
    )
    request.response_context.outcome = "EVIDENCE_UNAVAILABLE"
    result = await GuardedResponseProvider().generate(request)
    assert "check the recorded overview" in result.text
    assert "reported uses" not in result.text


async def test_safety_question_does_not_imply_missing_data_means_safe():
    request = response_request(0)
    request.response_context.outcome = "SAFETY_ABSTENTION"
    request.response_context.user_question = "Is it safe? Are there side effects?"
    request.response_context.resolved_plant = CandidatePlant(
        plant_id="fixture-plant", label="Neem", confidence=1
    )
    result = await GuardedResponseProvider().generate(request)
    assert "don't have enough reliable safety information" in result.text
    assert "Neem" in result.text
    assert "qualified clinician" in result.text


async def test_reported_uses_group_by_part_without_promoting_anatomy_terms():
    request = response_request(0)
    request.response_context.resolved_plant = CandidatePlant(
        plant_id="fixture-plant", label="Neem", confidence=1
    )
    entries = [
        ("Bronchitis", "fruit", "Diseases"),
        ("Common cold", "fruit", "Diseases"),
        ("Pectoralis muscles", "fruit", "Anatomy"),
    ]
    request.response_context.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps({"therapeutic_use": term, "mesh_category_name": category}),
            graph_nodes=[{"plant_part": part}],
            confidence=1,
            provenance=Provenance(
                source_id=f"fixture:{index}",
                source_type="neo4j",
                reference="GET_THERAPEUTIC_USES:fixture",
            ),
        )
        for index, (term, part, category) in enumerate(entries)
    ]
    result = await GuardedResponseProvider().generate(request)
    assert "**Fruit:** Bronchitis [1], Common cold [2]" in result.text
    assert "Pectoralis muscles" not in result.text
    assert len(result.citation_ids) == 2
    assert "not proof that the plant treats" in result.text


async def test_compound_answer_explains_term_and_combines_plant_locations():
    request = response_request(0)
    request.response_context.intent = "GET_PHYTOCHEMICAL_DETAILS"
    request.response_context.user_question = "What is Kaempferol?"
    request.response_context.resolved_plant = CandidatePlant(
        plant_id="fixture-plant", label="Moringa oleifera", confidence=1
    )
    request.response_context.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps(
                {"phytochemical_name": "Kaempferol", "classyfire_class": "Flavonoids"}
            ),
            graph_nodes=[{"plant_part": part}],
            confidence=1,
            provenance=Provenance(
                source_id=part, source_type="neo4j", reference="GET_PHYTOCHEMICAL_DETAILS:fixture"
            ),
        )
        for part in ("flower", "fruit")
    ]
    answer = await GuardedResponseProvider().generate(request)
    assert "chemical found in plants" in answer.text
    assert "broad group of plant compounds" in answer.text
    assert "flower [1]" in answer.text and "fruit [2]" in answer.text
    assert "strength of evidence" not in answer.text
    assert "not medical advice" not in answer.text
    assert len(answer.citation_ids) == 2


async def test_use_answer_separates_disease_terms_from_other_catalog_topics():
    request = response_request(0)
    request.response_context.resolved_plant = CandidatePlant(
        plant_id="fixture-plant", label="Moringa oleifera", confidence=1
    )
    request.response_context.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps({"therapeutic_use": term, "mesh_category_name": category}),
            graph_nodes=[{"plant_part": "bark"}],
            confidence=1,
            provenance=Provenance(
                source_id=term.replace(" ", "_"),
                source_type="neo4j",
                reference="GET_THERAPEUTIC_USES:fixture",
            ),
        )
        for term, category in (("Common cold", "Diseases"), ("Antioxidants", "Chemicals and Drugs"))
    ]
    answer = await GuardedResponseProvider().generate(request)
    assert "**Bark:** Common cold [1]" in answer.text
    assert "**Bark · related topics:** Antioxidants [2]" in answer.text
    assert "rather than illnesses" in answer.text
    assert "not evidence that the plant treats" in answer.text


async def test_bioactivity_answer_explains_ic50_without_clinical_claim():
    request = response_request(0)
    request.response_context.intent = "GET_BIOACTIVITY"
    request.response_context.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps(
                {"standard_type": "IC50", "standard_value": 42, "standard_units": "nM"}
            ),
            graph_nodes=[{"phytochemical_name": "Kaempferol"}],
            confidence=1,
            provenance=Provenance(
                source_id="assay", source_type="neo4j", reference="GET_BIOACTIVITY:fixture"
            ),
        )
    ]
    answer = await GuardedResponseProvider().generate(request)
    assert "IC50" in answer.text
    assert "50% inhibition" in answer.text
    assert "laboratory" in answer.text
    assert "whether the plant helps a person" in answer.text
    assert "42 nM" in answer.text


@pytest.mark.parametrize(
    ("kind", "field", "first", "second", "expected"),
    [
        ("GET_PLANT_PARTS", "plant_part", "leaf", "root", "Leaf [1], Root [2]"),
        (
            "GET_PHYTOCHEMICALS",
            "phytochemical_name",
            "Nimbin",
            "Quercetin",
            "**Leaf:** Nimbin [1], Quercetin [2]",
        ),
    ],
)
async def test_multiple_short_facts_are_readable_and_keep_citations(
    kind, field, first, second, expected
):
    request = response_request(0)
    request.response_context.intent = kind
    request.response_context.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps({field: value}),
            graph_nodes=[{"plant_part": value if kind == "GET_PLANT_PARTS" else "leaf"}],
            confidence=1,
            provenance=Provenance(
                source_id=f"fixture:{index}", source_type="neo4j", reference=f"{kind}:fixture"
            ),
        )
        for index, value in enumerate((first, second))
    ]
    result = await GuardedResponseProvider().generate(request)
    assert expected in result.text
    assert len(result.citation_ids) == 2


async def test_part_followup_explains_each_recorded_part_without_inventing_uses():
    request = response_request(0)
    request.response_context.intent = "GET_PLANT_PARTS"
    request.response_context.user_question = "Explain each"
    request.response_context.answer_style = "explanation"
    request.response_context.graph_evidence = [
        Evidence(
            modality="graph",
            claim=json.dumps({"plant_part": part}),
            graph_nodes=[{"plant_part": part}],
            confidence=1,
            provenance=Provenance(
                source_id=f"fixture:{part}",
                source_type="neo4j",
                reference="GET_PLANT_PARTS:fixture",
            ),
        )
        for part in ("leaf", "root")
    ]
    answer = concise_answer(request.response_context, answer_facts(request.response_context))
    assert answer is not None
    assert "**Leaf:** A leaf is foliage. [1]" in answer.text
    assert "**Root:** A root is a below-ground structure. [2]" in answer.text
    assert "does not itself describe a use or an effect" in answer.text
    assert len(answer.citation_ids) == 2


@pytest.mark.parametrize(
    "frames",
    [
        [{"message": {"content": '{"blocks":[]}'}, "done": True}],
        [{"message": {"content": "part"}}, {"message": {"content": "end"}, "done": True}],
    ],
)
async def test_ollama_transport_uses_bounded_structured_stream(frames):
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] and body["think"] is False
        assert body["options"]["num_ctx"] == 4096
        assert "tools" not in body
        return httpx.Response(200, text="\n".join(json.dumps(f) for f in frames))

    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        llm_model="fixture:model",
        ollama_base_url="http://localhost:11434",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=settings.ollama_base_url
    ) as client:
        model = OllamaModel(settings, client)
        output = "".join([t async for t in model.tokens("prepared", {"type": "object"})])
        assert output == "".join(f["message"]["content"] for f in frames)


async def test_ollama_reserves_bounded_output_for_multi_item_explanations():
    def handler(request):
        body = json.loads(request.content)
        assert body["options"]["num_predict"] == 1024
        return httpx.Response(
            200, text=json.dumps({"message": {"content": "{}"}, "done": True})
        )

    settings = Settings(
        _env_file=None, llm_provider="ollama", llm_model="fixture:model",
        ollama_base_url="http://localhost:11434", llm_output_tokens=512,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=settings.ollama_base_url
    ) as client:
        schema = {"properties": {"explanations": {"maxItems": 8}}}
        output = "".join(
            [token async for token in OllamaModel(settings, client).tokens("", schema)]
        )
        assert output == "{}"


@pytest.mark.parametrize(
    "frame",
    [
        [],
        {"message": []},
        {"message": {"content": 123}},
        {"message": {"tool_calls": [{"name": "database"}]}},
        {"error": "secret"},
        {"message": {"content": "partial"}},
        {"done": True, "done_reason": "length"},
    ],
)
async def test_ollama_rejects_invalid_incomplete_and_tool_frames(frame):
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        llm_model="fixture:model",
        ollama_base_url="http://localhost:11434",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=frame)),
        base_url=settings.ollama_base_url,
    ) as client:
        with pytest.raises(ValueError):
            _ = [t async for t in OllamaModel(settings, client).tokens("prepared", {})]
