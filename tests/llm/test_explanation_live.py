"""Opt-in check for the configured local model's explanation behavior."""

import json
import os

import pytest

from backend.config.settings import Settings
from backend.contracts.agents import CandidatePlant
from backend.contracts.evidence import Evidence, Provenance
from backend.contracts.response import FinalResponseRequest, ResponseContext
from backend.llm.guarded import GuardedResponseProvider
from backend.llm.knowledge_explanation import explanation_packet, validate_explanations
from backend.llm.ollama import OllamaModel
from backend.llm.verbalize import answer_facts

pytestmark = pytest.mark.skipif(
    os.getenv("RESPONSE_RUN_INTEGRATION") != "1", reason="Local opt-in"
)


@pytest.mark.parametrize(
    ("kind", "claim", "nodes", "question"),
    [
        (
            "GET_PHYTOCHEMICALS",
            {"phytochemical_name": "Kaempferol", "classyfire_class": "Flavonoids"},
            [{"plant_part": "leaf"}],
            "Explain this phytochemical in simple terms",
        ),
        (
            "GET_PLANT_PARTS", {"plant_part": "leaf"},
            [{"plant_part": "leaf"}], "What does this plant part mean?",
        ),
        (
            "GET_THERAPEUTIC_USES", {"therapeutic_use": "Cough"},
            [{"plant_part": "leaf"}], "Explain what this use term means",
        ),
        (
            "GET_BIOACTIVITY",
            {"standard_type": "IC50", "standard_value": "20", "standard_units": "nM"},
            [{"phytochemical_name": "Kaempferol"}],
            "What does this measurement mean?",
        ),
    ],
)
async def test_configured_model_explains_without_turning_background_into_citation(
    kind: str, claim: dict[str, str], nodes: list[dict[str, str]], question: str
) -> None:
    settings = Settings()
    assert settings.llm_provider == "ollama"
    model = OllamaModel(settings)
    try:
        assert await model.health()
        evidence = Evidence(
            modality="graph",
            claim=json.dumps(claim),
            graph_nodes=nodes,
            confidence=1,
            provenance=Provenance(
                source_id="fixture:plant", source_type="neo4j",
                reference=f"{kind}:fixture",
            ),
        )
        request = FinalResponseRequest(response_context=ResponseContext(
                intent=kind,
                user_question=question,
                answer_style="explanation",
                resolved_plant=CandidatePlant(
                    plant_id="fixture:plant", label="Basella alba", confidence=1
                ),
                graph_evidence=[evidence],
                outcome="Objectives satisfied",
            ))
        if os.getenv("RESPONSE_CAPTURE_OUTPUT") == "1":
            facts = answer_facts(request.response_context)
            prompt, schema = explanation_packet(request.response_context, facts)
            raw = "".join([chunk async for chunk in model.tokens(prompt, schema)])
            print("\nraw explanation:", raw)
            try:
                validate_explanations(raw, request.response_context, facts)
            except ValueError as error:
                print("validation:", error)
        response = await GuardedResponseProvider(model).generate(request)
        if os.getenv("RESPONSE_CAPTURE_OUTPUT") == "1":
            print(
                f"\nprovider={response.provider} fallback={response.fallback_used}"
                f"\n{response.text}"
            )
        assert response.citation_ids == [evidence.evidence_id]
        assert any(term in response.text for term in ("Kaempferol", "leaf", "Cough", "IC50"))
        assert "cure" not in response.text.casefold()
    finally:
        await model.close()
