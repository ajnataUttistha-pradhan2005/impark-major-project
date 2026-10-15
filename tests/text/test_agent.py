from uuid import uuid4

import pytest

from backend.agents.text.agent import TextAgent
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


async def test_safety(name_search):
    output = await TextAgent(name_search).execute(request("What dose of neem should I take?"))
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
