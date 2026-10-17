from uuid import uuid4

import pytest

from backend.agents.text.agent import TextAgent
from backend.agents.text.intent_model import IntentSuggestion
from backend.contracts.actions import Action, ActionName, AgentInvocation, Capability
from backend.contracts.agents import Observation, QueryType, TextAgentInput
from backend.contracts.base import CorrelationMetadata


def request(text, **kwargs):
    return TextAgentInput(
        text=text,
        invocation=AgentInvocation(
            correlation=CorrelationMetadata(session_id=uuid4()),
            action=Action(name=ActionName.RESOLVE_TEXT_ENTITY),
            capability=Capability.TEXT,
        ),
        **kwargs,
    )


@pytest.mark.parametrize(
    "text,intent,part",
    [
        ("What compounds are in neem leaves?", QueryType.GET_PHYTOCHEMICALS, "leaf"),
        ("Tell me about neem", QueryType.GET_PLANT_DETAILS, None),
        ("Medicinal uses of tulsi roots", QueryType.GET_THERAPEUTIC_USES, "root"),
        ("Sources for neem", QueryType.GET_DOCUMENTS, None),
        ("Which protein targets for neem?", QueryType.GET_PROTEIN_TARGETS, None),
        ("Bioactivity of neem", QueryType.GET_BIOACTIVITY, None),
    ],
)
async def test_intents(name_search, text, intent, part):
    output = await TextAgent(name_search).execute(request(text))
    assert isinstance(output, Observation)
    assert intent in output.payload.query_types
    assert output.payload.part == part


async def test_coreference_and_explicit_switch(name_search):
    active = (await name_search.search("neem"))[0]
    agent = TextAgent(name_search)
    output = await agent.execute(request("What are its uses?", active_plant=active))
    assert output.payload.candidates[0].plant_id == active.plant_id
    output = await agent.execute(request("What about tulsi?", active_plant=active))
    assert output.payload.scope_rejected
    assert not output.payload.candidates
    output = await agent.execute(
        request("What phytochemicals does it contain?", active_plant=active)
    )
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert QueryType.GET_PHYTOCHEMICALS in output.payload.query_types


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What evidence do we have?", QueryType.GET_EVIDENCE),
        ("What clinical evidence is available?", QueryType.GET_EVIDENCE),
        ("Tell me more about its uses", QueryType.GET_THERAPEUTIC_USES),
        ("Which protein targets are recorded?", QueryType.GET_PROTEIN_TARGETS),
        ("give me medical benefits of this plant", QueryType.GET_THERAPEUTIC_USES),
        ("give me medical benifits of this plant", QueryType.GET_THERAPEUTIC_USES),
        ("Any benfits from this plant?", QueryType.GET_THERAPEUTIC_USES),
        ("What health benefits does it have?", QueryType.GET_THERAPEUTIC_USES),
        ("What do those numbers and target names mean?", QueryType.GET_BIOACTIVITY),
    ],
)
async def test_active_plant_is_kept_for_natural_followups(name_search, question, expected):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(request(question, active_plant=active))
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert output.payload.candidates[0].match_method == "coreference"
    assert expected in output.payload.query_types
    assert not output.payload.needs_clarification


async def test_assay_number_followup_retains_targets_inside_bioactivity(name_search):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(
        request("What do those numbers and target names mean?", active_plant=active)
    )
    assert output.payload.query_types == [QueryType.GET_BIOACTIVITY]


@pytest.mark.parametrize(
    "question",
    [
        "explain those",
        "what do they mean",
        "go on",
        "explain each",
        "explain every one",
        "break them down",
        "walk through each",
        "What does this property mean?",
    ],
)
async def test_elliptical_followup_reuses_last_topic_without_reidentification(
    name_search, question
):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(
        request(question, active_plant=active, recent_query_types=[QueryType.GET_BIOACTIVITY])
    )
    assert output.payload.query_types == [QueryType.GET_BIOACTIVITY]
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert "topic_coreference" in output.payload.stages
    assert not output.payload.needs_clarification


async def test_explain_each_part_keeps_last_topic_and_locked_plant(name_search):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(
        request(
            "explain each",
            active_plant=active,
            recent_query_types=[QueryType.GET_PLANT_PARTS],
        )
    )
    assert output.payload.query_types == [QueryType.GET_PLANT_PARTS]
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert not output.payload.needs_clarification


@pytest.mark.parametrize(
    "question",
    [
        "What medical benefits are documented?",
        "Which parts can I read about?",
        "Are there any linked studies?",
        "What evidence is available?",
        "Can you explain its reported uses in plain language?",
        "What about the protein targets?",
    ],
)
async def test_unnamed_followup_never_restarts_plant_discovery(name_search, question):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(request(question, active_plant=active))
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert output.payload.candidates[0].match_method == "coreference"
    assert not output.payload.needs_clarification
    assert not output.payload.scope_rejected


async def test_active_plant_reference_does_not_override_explicit_other_plant(name_search):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(
        request("Compare this plant with tulsi", active_plant=active)
    )
    assert output.payload.scope_rejected


async def test_unknown_followup_asks_for_topic_not_plant_identity(name_search):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(
        request("Explain the zapper of this plant", active_plant=active)
    )
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert output.payload.intent_uncertain
    assert "plant details" in output.payload.clarification_question
    assert "scientific/common name" not in output.payload.clarification_question


async def test_safety(name_search):
    output = await TextAgent(name_search).execute(request("What dose of neem should I take?"))
    assert output.payload.safety_abstention
    output = await TextAgent(name_search).execute(request("Are there side effects?"))
    assert output.payload.safety_abstention


async def test_reassessment_cannot_reuse_weakened_identity(name_search):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(
        request(
            "neem", reassessment=True, active_plant=active, excluded_plant_ids=[active.plant_id]
        )
    )
    assert not output.payload.candidates


async def test_short_followup_and_unsupported_intent(name_search):
    active = (await name_search.search("neem"))[0]
    agent = TextAgent(name_search)
    output = await agent.execute(request("and uses?", active_plant=active))
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert output.payload.candidates[0].match_method == "coreference"
    output = await agent.execute(request("Can neem predict tomorrow's weather?"))
    assert output.payload.intent_uncertain
    assert output.payload.needs_clarification
    assert "compounds" in output.payload.clarification_question


async def test_negated_intent_and_multiple_part_scope(name_search):
    agent = TextAgent(name_search)
    output = await agent.execute(request("Neem uses, not compounds"))
    assert output.payload.query_types == [QueryType.GET_THERAPEUTIC_USES]
    output = await agent.execute(request("Compounds in neem leaves and roots"))
    assert output.payload.intent_uncertain
    assert output.payload.part is None
    assert output.payload.clarification_question == "Which plant part should I retrieve first?"


@pytest.mark.parametrize(
    ("question", "suggested"),
    [
        ("What illnesses is it traditionally associated with?", QueryType.GET_THERAPEUTIC_USES),
        ("Which molecules have researchers found?", QueryType.GET_PHYTOCHEMICALS),
        ("Where was this finding published?", QueryType.GET_DOCUMENTS),
        ("How did it perform in laboratory testing?", QueryType.GET_BIOACTIVITY),
    ],
)
async def test_model_suggestion_is_typed_and_keeps_locked_plant(name_search, question, suggested):
    class Suggestion:
        async def suggest(self, text, previous, active_plant):
            assert text == question and active_plant
            return IntentSuggestion(query_types=[suggested], confidence=0.91)

    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search, Suggestion()).execute(
        request(question, active_plant=active)
    )
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert suggested in output.payload.query_types
    assert "model_intent_suggestion" in output.payload.stages
    assert not output.payload.needs_clarification


async def test_clear_intent_skips_model_and_topic_reuse_is_bounded(name_search):
    class Suggestion:
        calls = 0

        async def suggest(self, text, previous, active_plant):
            self.calls += 1
            return IntentSuggestion(reuse_previous_topic=True, confidence=0.9)

    model = Suggestion()
    active = (await name_search.search("neem"))[0]
    agent = TextAgent(name_search, model)
    explicit = await agent.execute(request("What compounds are recorded?", active_plant=active))
    assert explicit.payload.query_types == [QueryType.GET_PHYTOCHEMICALS]
    assert model.calls == 0
    followup = await agent.execute(
        request("Could you expand on that?", active_plant=active,
                recent_query_types=[QueryType.GET_PHYTOCHEMICALS])
    )
    assert followup.payload.query_types == [QueryType.GET_PHYTOCHEMICALS]
    assert followup.payload.candidates[0].plant_id == active.plant_id


@pytest.mark.parametrize(
    "previous_type",
    [QueryType.GET_THERAPEUTIC_USES, QueryType.GET_PHYTOCHEMICALS],
)
async def test_part_followup_reuses_topic_but_changes_scope(name_search, previous_type):
    active = (await name_search.search("neem"))[0]
    output = await TextAgent(name_search).execute(
        request(
            "What about the leaves?",
            active_plant=active,
            recent_query_types=[previous_type],
        )
    )
    assert output.payload.query_types == [previous_type]
    assert output.payload.part == "leaf"
    assert output.payload.candidates[0].plant_id == active.plant_id
    assert not output.payload.needs_clarification
