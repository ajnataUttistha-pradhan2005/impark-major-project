from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.agents.text.open_question import OpenPlantQuestionTextAgent
from backend.agents.text.search import HybridNameSearch
from backend.contracts.actions import Action, ActionName, AgentInvocation, Capability
from backend.contracts.agents import CandidatePlant, Observation, TextAgentInput, TextResult
from backend.contracts.base import CorrelationMetadata
from backend.contracts.response import FinalResponseRequest, ResponseContext
from backend.evidence.plant_context import PlantContextLoader
from backend.llm.plant_context import PlantContextResponseProvider
from backend.services.conversations import ConversationService


class FakePostgres:
    async def scalar(self, query, plant_id):
        assert "plant_id=$1" in query
        assert plant_id is not None
        return "Basella alba"


class FakeGraph:
    def __init__(self):
        self.queries = []

    async def read(self, query, parameters, *, timeout_seconds):
        self.queries.append((query, parameters, timeout_seconds))
        assert parameters["name"] == "Basella alba"
        assert "$name" in query and "LIMIT $limit" in query
        return [{"nodes": [{"plant_name": "Basella alba"}], "relationships": []}]


class FakeModel:
    name = "test-model"

    async def freeform(self, prompt):
        assert "Basella alba" in prompt
        assert "What are its uses?" in prompt
        yield "A natural answer from the model."


@pytest.mark.asyncio
async def test_plant_context_reads_all_fixed_categories():
    graph = FakeGraph()
    rows, truncated = await PlantContextLoader(graph, FakePostgres()).load(str(uuid4()))
    assert len(graph.queries) == 8
    assert len(rows) == 8
    assert not truncated
    assert all("Basella alba" not in query for query, _, _ in graph.queries)


@pytest.mark.asyncio
async def test_plant_context_response_uses_model_without_invented_citations():
    request = FinalResponseRequest(
        response_context=ResponseContext(
            intent="GET_THERAPEUTIC_USES",
            user_question="What are its uses?",
            outcome="Objectives satisfied",
            resolved_plant=CandidatePlant(
                plant_id=str(uuid4()), label="Basella alba", confidence=1
            ),
            plant_context=[{"nodes": [{"plant_name": "Basella alba"}], "relationships": []}],
        )
    )
    response = await PlantContextResponseProvider(FakeModel()).generate(request)
    assert response.text == "A natural answer from the model."
    assert response.citation_ids == []
    assert response.provider == "ollama-plant-context"


@pytest.mark.asyncio
async def test_unknown_locked_plant_question_reaches_freeform_response():
    class Delegate:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(
                    placeholder=False,
                    intent_uncertain=True,
                    needs_clarification=True,
                    candidates=[request.active_plant],
                ),
            )

    plant = CandidatePlant(plant_id=str(uuid4()), label="Basella alba", confidence=1)
    invocation = AgentInvocation(
        correlation=CorrelationMetadata(session_id=uuid4()),
        action=Action(name=ActionName.RESOLVE_TEXT_ENTITY),
        capability=Capability.TEXT,
    )
    request = TextAgentInput(
        invocation=invocation,
        text="What else can you tell me about its ecology?",
        active_plant=plant,
    )
    result = await OpenPlantQuestionTextAgent(Delegate()).execute(request)
    assert isinstance(result, Observation)
    assert result.payload.queries[0].parameters.plant_id == plant.plant_id
    assert not result.payload.needs_clarification


@pytest.mark.asyncio
async def test_freeform_wrapper_preserves_discovery_search_provider():
    class Delegate:
        def __init__(self):
            self.provider = HybridNameSearch(FakePostgres())

    delegate = Delegate()
    wrapped = OpenPlantQuestionTextAgent(delegate)
    assert wrapped.provider is delegate.provider
    assert isinstance(wrapped.provider, HybridNameSearch)

    async def suggestions(query):
        assert query == "basel"
        return []

    delegate.provider.autocomplete = suggestions
    service = SimpleNamespace(harness=SimpleNamespace(execution=SimpleNamespace(text=wrapped)))
    response = await ConversationService.autocomplete(service, "basel")
    assert response.implemented
