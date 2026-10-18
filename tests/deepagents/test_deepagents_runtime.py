import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.contracts.actions import Capability
from backend.contracts.agents import CandidatePlant, GraphAgentOutput, Observation
from backend.contracts.evidence import Evidence, Modality, Provenance
from backend.orchestrator.deepagents.runtime import DeepAgentRuntime
from backend.state.models import ConversationState, SessionMode, TaskStatus


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("previous_question", "expected_query", "claim", "label"),
    [
        (
            "Tell me about this plant",
            "GET_PLANT_DETAILS",
            {"common_names": "Malabar spinach"},
            "Malabar spinach",
        ),
        (
            "What are its other names and aliases?",
            "GET_PLANT_ALIASES",
            {"alias": "Malabar spinach", "alias_type": "common"},
            "Malabar spinach",
        ),
        (
            "Which plant parts are recorded?",
            "GET_PLANT_PARTS",
            {"plant_part": "leaf"},
            "leaf",
        ),
        (
            "List its phytochemicals",
            "GET_PHYTOCHEMICALS",
            {"phytochemical_name": "Betacyanin"},
            "Betacyanin",
        ),
        (
            "What does bioactivity mean for this plant?",
            "GET_BIOACTIVITY",
            {"bioactivity_id": "activity-1", "standard_type": "IC50"},
            "IC50",
        ),
        (
            "What protein targets are recorded?",
            "GET_PROTEIN_TARGETS",
            {"target_name": "Synthetic target"},
            "Synthetic target",
        ),
        (
            "What uses are reported for this plant?",
            "GET_THERAPEUTIC_USES",
            {"therapeutic_use": "Synthetic use"},
            "Synthetic use",
        ),
        (
            "Which documents or papers support these records?",
            "GET_DOCUMENTS",
            {"document_title": "Synthetic paper"},
            "Synthetic paper",
        ),
    ],
)
async def test_followup_repairs_missed_topic_retrieval(
    monkeypatch, previous_question, expected_query, claim, label
):
    import backend.orchestrator.deepagents.runtime as module
    from backend.state.models import DialogueTurn

    plant = CandidatePlant(plant_id=str(uuid4()), label="Basella alba", confidence=1)
    evidence = Evidence(
        modality=Modality.GRAPH,
        claim=json.dumps(claim),
        confidence=1,
        provenance=Provenance(
            source_id=plant.plant_id, source_type="neo4j", reference=expected_query
        ),
        graph_scope={"plant_id": plant.plant_id},
    )
    called = []

    class Graph:
        async def execute(self, request):
            called.append(request.query.query_type.value)
            return Observation(
                invocation=request.invocation,
                component=Capability.GRAPH,
                payload=GraphAgentOutput(placeholder=False, evidence=[evidence]),
            )

    class Model:
        model = "fixture"

        async def ainvoke(self, messages):
            content = f"The recorded result is {label} [{evidence.evidence_id}]."
            return SimpleNamespace(content=content)

    class Orchestrator:
        async def ainvoke(self, payload, config):
            return {"messages": [SimpleNamespace(content="I couldn't find the requested records.")]}

    monkeypatch.setattr(module, "create_agent", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        module, "create_deep_agent", lambda **kwargs: Orchestrator()
    )
    monkeypatch.setattr(module, "register_harness_profile", lambda *args: None)
    harness = SimpleNamespace(
        execution=SimpleNamespace(text=None, image=None, graph=Graph()),
        emit=lambda state, event: None,
    )
    settings = SimpleNamespace(
        entity_auto_resolve_threshold=0.95,
        action_timeout_seconds=10,
        agent_main_model_provider="ollama",
    )
    state = ConversationState.new()
    state.context.active_plant = plant
    state.session.locked_plant_id = plant.plant_id
    state.session.mode = SessionMode.CONVERSATION
    state.context.recent_dialogue = [
        DialogueTurn(question="List phytochemicals", answer="Several compounds were listed."),
        DialogueTurn(question=previous_question, answer="I couldn't find records."),
    ]
    state.user_message = "try again" if expected_query == "GET_PLANT_ALIASES" else "more records"
    result = await DeepAgentRuntime(
        harness, SimpleNamespace(get=lambda role: Model()), settings
    ).run(state)
    assert called == [expected_query]
    assert label in result.response.text
    assert "couldn't find" not in result.response.text
    assert result.context.recent_dialogue[-1].query_types[0].value == expected_query


@pytest.mark.asyncio
async def test_four_agent_runtime_preserves_session_and_evidence(monkeypatch):
    import backend.orchestrator.deepagents.runtime as module

    plant = CandidatePlant(plant_id=str(uuid4()), label="Basella alba", confidence=0.99)

    class Search:
        async def resolve(self, text, limit):
            assert text == "Basella alba"
            return [plant], ["exact_alias"]

    class Graph:
        async def execute(self, request):
            evidence = Evidence(
                modality=Modality.GRAPH,
                claim=json.dumps({"plant_name": plant.label}),
                confidence=1,
                provenance=Provenance(
                    source_id=plant.plant_id, source_type="neo4j", reference="GET_PLANT_DETAILS"
                ),
                graph_scope={"plant_id": plant.plant_id},
            )
            return Observation(
                invocation=request.invocation,
                component=Capability.GRAPH,
                payload=GraphAgentOutput(placeholder=False, evidence=[evidence]),
            )

    monkeypatch.setattr(module, "HybridNameSearch", Search)

    class FakeAgent:
        def __init__(self, tools):
            self.tools = tools

    def create_agent(*, model, tools, system_prompt):
        return FakeAgent(tools)

    class Orchestrator:
        def __init__(self, subagents):
            self.subagents = {agent["name"]: agent["runnable"] for agent in subagents}

        async def ainvoke(self, payload, config):
            await self.subagents["text_entity"].tools[0].ainvoke({"text": "Basella alba"})
            graph_result = (
                await self.subagents["knowledge_graph"]
                .tools[0]
                .ainvoke({"query_type": "GET_PLANT_DETAILS"})
            )
            cited = json.loads(graph_result)["facts"][0]["citation_id"]
            return {"messages": [SimpleNamespace(content=f"Basella alba is listed. [{cited}]")]}

    monkeypatch.setattr(module, "create_agent", create_agent)
    monkeypatch.setattr(
        module,
        "create_deep_agent",
        lambda *, model, subagents, system_prompt: Orchestrator(subagents),
    )
    monkeypatch.setattr(module, "register_harness_profile", lambda *args: None)
    harness = SimpleNamespace(
        execution=SimpleNamespace(
            text=SimpleNamespace(provider=Search()),
            graph=Graph(),
            image=None,
        ),
        emit=lambda state, event: None,
    )
    models = SimpleNamespace(get=lambda role: SimpleNamespace(model=role))
    settings = SimpleNamespace(
        entity_auto_resolve_threshold=0.95,
        action_timeout_seconds=45,
        agent_main_model_provider="ollama",
    )
    state = ConversationState.new()
    state.user_message = "Basella alba"
    result = await DeepAgentRuntime(harness, models, settings).run(state)
    assert result.session.mode == SessionMode.CONVERSATION
    assert result.session.locked_plant_id == plant.plant_id
    assert result.termination.status == TaskStatus.COMPLETE
    assert result.response.citation_ids == [result.evidence.graph[0].evidence_id]
    assert result.response.text.endswith("[1]")
    assert len(result.execution.observations) == 2


@pytest.mark.asyncio
async def test_empty_model_answer_uses_retrieved_facts(monkeypatch):
    import backend.orchestrator.deepagents.runtime as module

    plant = CandidatePlant(plant_id=str(uuid4()), label="Basella alba", confidence=1)

    class Graph:
        async def execute(self, request):
            evidence = Evidence(
                modality=Modality.GRAPH,
                claim=json.dumps({"plant_name": plant.label}),
                confidence=1,
                provenance=Provenance(
                    source_id=plant.plant_id,
                    source_type="neo4j",
                    reference="GET_PLANT_DETAILS: Basella alba",
                ),
                graph_scope={"plant_id": plant.plant_id},
                graph_nodes=[{"plant_name": plant.label}],
            )
            return Observation(
                invocation=request.invocation,
                component=Capability.GRAPH,
                payload=GraphAgentOutput(placeholder=False, evidence=[evidence]),
            )

    class EmptyAgent:
        async def ainvoke(self, payload, config):
            return {"messages": [SimpleNamespace(content="")]}

    monkeypatch.setattr(module, "create_agent", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(module, "create_deep_agent", lambda **kwargs: EmptyAgent())
    monkeypatch.setattr(module, "register_harness_profile", lambda *args: None)
    harness = SimpleNamespace(
        execution=SimpleNamespace(text=SimpleNamespace(provider=None), graph=Graph(), image=None),
        emit=lambda state, event: None,
    )
    models = SimpleNamespace(get=lambda role: SimpleNamespace(model=role))
    settings = SimpleNamespace(action_timeout_seconds=45, agent_main_model_provider="ollama")
    state = ConversationState.new()
    state.session.mode = SessionMode.CONVERSATION
    state.context.active_plant = plant
    state.session.locked_plant_id = plant.plant_id
    state.user_message = "Tell me about this plant"
    result = await DeepAgentRuntime(harness, models, settings).run(state)
    assert result.response.text
    assert result.response.fallback_used
    assert result.evidence.graph


@pytest.mark.asyncio
async def test_verified_selection_confirms_without_model_call():
    plant = CandidatePlant(plant_id=str(uuid4()), label="Moringa oleifera", confidence=1)
    state = ConversationState.new()
    state.context.active_plant = plant
    state.user_message = plant.label

    class Models:
        def get(self, role):
            raise AssertionError("Plant confirmation should not load a model")

    harness = SimpleNamespace(emit=lambda state, event: None)
    result = await DeepAgentRuntime(harness, Models(), SimpleNamespace()).run(state)
    assert result.session.mode == SessionMode.CONVERSATION
    assert result.session.locked_plant_id == plant.plant_id
    assert "Moringa oleifera" in result.response.text


@pytest.mark.asyncio
async def test_length_stopped_answer_is_completed_before_return(monkeypatch):
    import backend.orchestrator.deepagents.runtime as module

    class Model:
        model = "test"

        async def ainvoke(self, messages):
            return SimpleNamespace(
                content="In plants generally, leaf form reflects growth conditions.",
                response_metadata={"done_reason": "stop"},
            )

    class TruncatedAgent:
        async def ainvoke(self, payload, config):
            return {
                "messages": [
                    SimpleNamespace(
                        content="An unfinished answer [",
                        response_metadata={"done_reason": "length"},
                    )
                ]
            }

    monkeypatch.setattr(module, "create_agent", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(module, "create_deep_agent", lambda **kwargs: TruncatedAgent())
    monkeypatch.setattr(module, "register_harness_profile", lambda *args: None)
    plant = CandidatePlant(plant_id=str(uuid4()), label="Basella alba", confidence=1)
    state = ConversationState.new()
    state.session.mode = SessionMode.CONVERSATION
    state.context.active_plant = plant
    state.session.locked_plant_id = plant.plant_id
    state.user_message = "Why are its leaves shaped that way?"
    harness = SimpleNamespace(emit=lambda state, event: None, execution=SimpleNamespace())
    models = SimpleNamespace(get=lambda role: Model())
    settings = SimpleNamespace(action_timeout_seconds=45, agent_main_model_provider="ollama")
    result = await DeepAgentRuntime(harness, models, settings).run(state)
    assert result.response.provider == "deepagents"
    assert result.response.fallback_used is False
    assert result.response.text.startswith("In plants generally")
