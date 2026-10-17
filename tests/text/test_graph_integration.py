from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.agents.graph.agent import GraphAgent
from backend.agents.graph.retrieval import PlantGraphRetrieval
from backend.agents.text.agent import TextAgent
from backend.api.schemas.chat import ChatRequest
from backend.contracts.actions import Capability
from backend.contracts.agents import Observation
from backend.contracts.response import ClarificationResponse
from backend.database.neo4j.errors import GraphDatabaseError
from backend.llm.grounded import GroundedResponseProvider
from backend.services.errors import ServiceError


@pytest.fixture
def graph_service(service, name_search):
    graph, pg = AsyncMock(), AsyncMock()
    pg.scalar.return_value = "Fixture neem"
    graph.read.return_value = [
        {
            "fact": {"phytochemical_name": "Synthetic compound", "inchi_key": "fixture:compound"},
            "nodes": [
                {"plant_name": "Fixture neem"},
                {"plant_part_id": "fixture:part"},
                {"inchi_key": "fixture:compound", "phytochemical_name": "Synthetic compound"},
            ],
            "relations": ["HAS_PART", "CONTAINS"],
        }
    ]
    service.harness.execution.text = TextAgent(name_search)
    service.harness.execution.graph = GraphAgent(PlantGraphRetrieval(graph, pg))
    service.harness.llm = GroundedResponseProvider()
    return service, graph


@pytest.mark.parametrize(
    "text",
    [
        "What compounds are in neem leaves?",
        "Neem chemical composition please",
        "show phytochemicals for neem",
        "tell me about neem",
        "neem parts",
        "neem bioactivity",
        "neem protein targets",
        "neem references",
        "neem evidence",
        "what is neem leaf",
        "नीम compounds",
        "Nimba uses",
    ],
)
async def test_language_to_real_graph_adapter_through_harness(graph_service, text):
    service, graph = graph_service
    sid = (await service.create(uuid4())).correlation.session_id
    response = await service.submit(sid, ChatRequest(text=text), uuid4())
    assert response.status == "COMPLETE", response
    assert response.mode == "conversation" and response.response.citation_ids
    state = await service.load(sid)
    assert state.session.locked_plant_id == response.active_plant.plant_id
    assert graph.read.await_count == 1
    assert state.response_context.graph_evidence[0].evidence_type == "unknown"


async def test_first_question_survives_selection_and_citation_followup(graph_service, name_search):
    service, graph = graph_service
    selected = (await name_search.search("neem"))[0]
    sid = (await service.create(uuid4())).correlation.session_id
    first = await service.submit(
        sid,
        ChatRequest(selected_plant_id=selected.plant_id, text="What compounds are in its leaves?"),
        uuid4(),
    )
    assert first.status == "COMPLETE" and first.response.citation_ids
    second = await service.submit(
        sid, ChatRequest(text=f"Trace evidence {first.response.citation_ids[0]}"), uuid4()
    )
    assert second.status == "COMPLETE", second
    assert second.response.citation_ids == first.response.citation_ids
    assert graph.read.await_count == 1


async def test_locked_plant_benefits_followup_does_not_request_identity(graph_service):
    service, graph = graph_service
    sid = (await service.create(uuid4())).correlation.session_id
    first = await service.submit(sid, ChatRequest(text="neem"), uuid4())
    followup = await service.submit(
        sid, ChatRequest(text="give me medical benifits of this plant"), uuid4()
    )
    assert followup.mode == "conversation"
    assert followup.active_plant.plant_id == first.active_plant.plant_id
    assert followup.status != "WAITING_USER"
    assert followup.clarification is None
    assert graph.read.await_count == 1


async def test_chat_cannot_switch_text_selection_clarification_or_provider_result(
    graph_service, name_search
):
    service, graph = graph_service
    sid = (await service.create(uuid4())).correlation.session_id
    initial = await service.submit(sid, ChatRequest(text="neem"), uuid4())
    active = initial.active_plant.plant_id
    other = (await name_search.search("tulsi"))[0]
    for text in ["tulsi", "What are tulsi uses?", "compare neem and tulsi"]:
        rejected = await service.submit(sid, ChatRequest(text=text), uuid4())
        assert rejected.status == "SCOPE_REJECTED", rejected
        assert rejected.active_plant.plant_id == active
        assert "new chat" in rejected.response.text
    graph.read.assert_not_awaited()
    with pytest.raises(ServiceError) as error:
        await service.submit(sid, ChatRequest(selected_plant_id=other.plant_id), uuid4())
    assert error.value.code == "PLANT_SCOPE_LOCKED"

    # A third-party Text Agent also cannot silently replace the locked identity.
    class OtherPlant:
        async def execute(self, request):
            from backend.contracts.agents import TextResult

            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(placeholder=False, candidates=[other]),
            )

    service.harness.execution.text = OtherPlant()
    result = await service.submit(sid, ChatRequest(text="anything"), uuid4())
    assert result.status == "SCOPE_REJECTED" and result.active_plant.plant_id == active


async def test_ambiguous_discovery_keeps_question_on_resume(graph_service):
    service, graph = graph_service
    sid = (await service.create(uuid4())).correlation.session_id
    waiting = await service.submit(sid, ChatRequest(text="Brahmi compounds"), uuid4())
    assert waiting.status == "WAITING_USER" and waiting.mode == "discovery"
    assert graph.read.await_count == 0
    reply = ClarificationResponse(
        clarification_id=waiting.clarification.clarification_id,
        selected_plant_id=waiting.clarification.candidates[0].plant_id,
    )
    final = await service.submit(sid, ChatRequest(text=reply.text), uuid4(), reply)
    assert final.status == "COMPLETE" and final.response.citation_ids
    assert final.correlation.run_id == waiting.correlation.run_id


async def test_empty_data_stops_without_repeating_same_query(graph_service):
    service, graph = graph_service
    graph.read.return_value = []
    sid = (await service.create(uuid4())).correlation.session_id
    result = await service.submit(sid, ChatRequest(text="neem compounds"), uuid4())
    assert result.status == "EVIDENCE_UNAVAILABLE"
    assert graph.read.await_count == 1
    assert "don't currently have enough information" in result.response.text
    assert "EVIDENCE_UNAVAILABLE" not in result.response.text
    assert result.mode == "conversation"


async def test_transient_error_recovers_and_permanent_error_is_not_retried(graph_service):
    service, graph = graph_service
    rows = graph.read.return_value
    graph.read.side_effect = [GraphDatabaseError("UNAVAILABLE", "private", retryable=True), rows]
    sid = (await service.create(uuid4())).correlation.session_id
    result = await service.submit(sid, ChatRequest(text="neem compounds"), uuid4())
    assert result.status == "COMPLETE" and graph.read.await_count == 2
    graph.read.reset_mock()
    graph.read.side_effect = GraphDatabaseError("AUTHENTICATION", "private", retryable=False)
    result = await service.submit(sid, ChatRequest(text="neem compounds"), uuid4())
    assert result.status == "EVIDENCE_UNAVAILABLE" and graph.read.await_count == 1
    assert "private" not in result.model_dump_json()


async def test_two_objectives_keep_success_and_missing_evidence_separate(graph_service):
    service, graph = graph_service
    graph.read.side_effect = [graph.read.return_value, []]
    sid = (await service.create(uuid4())).correlation.session_id
    result = await service.submit(sid, ChatRequest(text="neem compounds and uses"), uuid4())
    assert result.status == "EVIDENCE_UNAVAILABLE"
    assert result.response.citation_ids and graph.read.await_count == 2
    state = await service.load(sid)
    assert len(state.goal.completed) == 2  # identity + compound objective
    assert len(state.evidence.gaps) == 1


async def test_conflicting_graph_properties_do_not_change_locked_identity(graph_service):
    from copy import deepcopy

    service, graph = graph_service
    conflict = deepcopy(graph.read.return_value[0])
    conflict["nodes"][-1]["phytochemical_name"] = "Different graph value"
    conflict["fact"]["phytochemical_name"] = "Different graph value"
    graph.read.return_value.append(conflict)
    sid = (await service.create(uuid4())).correlation.session_id
    result = await service.submit(sid, ChatRequest(text="neem compounds"), uuid4())
    state = await service.load(sid)
    assert result.status == "EVIDENCE_UNAVAILABLE"
    assert state.session.locked_plant_id == result.active_plant.plant_id
    assert graph.read.await_count == 1
    assert not state.belief.requires_reassessment
    assert "source details conflict" in result.response.text
    assert "graph identifier" not in result.response.text
    assert len(result.response.citation_ids) == 2


async def test_image_agent_cannot_replace_locked_plant(graph_service, name_search):
    from backend.contracts.agents import ImageAgentResult, ImageMetadata, ImageReference

    service, graph = graph_service
    sid = (await service.create(uuid4())).correlation.session_id
    active = (await service.submit(sid, ChatRequest(text="neem"), uuid4())).active_plant
    other = (await name_search.search("tulsi"))[0]

    class OtherImage:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.IMAGE,
                payload=ImageAgentResult(placeholder=False, candidates=[other]),
            )

    service.harness.execution.image = OtherImage()
    iid = uuid4()
    service.images[sid] = {
        iid: ImageReference(
            image_id=iid,
            metadata=ImageMetadata(mime_type="image/png", size_bytes=100, width=10, height=10),
        )
    }
    result = await service.submit(sid, ChatRequest(image_id=iid), uuid4())
    assert result.status == "SCOPE_REJECTED"
    assert result.active_plant.plant_id == active.plant_id
    graph.read.assert_not_awaited()


async def test_discovery_entity_objective_requires_plant_and_survives_clarification(graph_service):
    from backend.contracts.agents import ResolvedMention

    service, graph = graph_service
    service.harness.execution.text.provider.repository.entities = AsyncMock(
        return_value=[
            ResolvedMention(
                entity_id="fixture:compound",
                kind="compound",
                label="Synthetic compound",
                confidence=1,
            )
        ]
    )
    sid = (await service.create(uuid4())).correlation.session_id
    waiting = await service.submit(sid, ChatRequest(text="Details about quercetin"), uuid4())
    assert waiting.status == "WAITING_USER"
    graph.read.assert_not_awaited()
    reply = ClarificationResponse(
        clarification_id=waiting.clarification.clarification_id, text="neem"
    )
    final = await service.submit(sid, ChatRequest(text="neem"), uuid4(), reply)
    assert final.status == "COMPLETE" and final.response.citation_ids
    _, params = graph.read.call_args.args
    assert params["compound"] == "fixture:compound"
    assert params["name"] == "Fixture neem"


async def test_compound_followup_reuses_last_entity_within_locked_plant(graph_service):
    from backend.contracts.agents import ResolvedMention

    service, graph = graph_service
    service.harness.execution.text.provider.repository.entities = AsyncMock(
        side_effect=lambda text: (
            [
                ResolvedMention(
                    entity_id="fixture:compound",
                    kind="compound",
                    label="Synthetic compound",
                    confidence=1,
                )
            ]
            if "synthetic compound" in text.casefold()
            else []
        )
    )
    sid = (await service.create(uuid4())).correlation.session_id
    await service.submit(sid, ChatRequest(text="neem"), uuid4())
    first = await service.submit(sid, ChatRequest(text="What is Synthetic compound?"), uuid4())
    assert first.status == "COMPLETE"
    assert graph.read.call_args.args[1]["compound"] == "fixture:compound"
    followup = await service.submit(sid, ChatRequest(text="Tell me more about it"), uuid4())
    assert followup.status == "COMPLETE"
    assert followup.active_plant.plant_id == first.active_plant.plant_id
    assert graph.read.call_args.args[1]["compound"] == "fixture:compound"
    assert graph.read.await_count == 3  # first detail, then detail and activity
    state = await service.load(sid)
    assert state.context.active_topic == "compound"


@pytest.mark.parametrize(
    "token,phrase,stored",
    [
        ("leaf", "leaves", "leaf"),
        ("root", "roots", "root"),
        ("bark", "bark", "bark"),
        ("flower", "flowers", "flower"),
        ("seed", "seeds", "seed"),
        ("fruit", "fruits", "fruit"),
        ("stem", "stems", "stem"),
        ("rhizome", "rhizomes", "rhizome"),
        ("shoot", "shoots", "shoot"),
        ("tuber", "tubers", "tuber"),
        ("wood", "wood", "wood"),
        ("gall", "galls", "gall"),
        ("culture", "culture", "culture"),
        ("aerial_part", "aerial parts", "aerial part"),
        ("plant_exudate", "exudates", "plant exudate"),
        ("whole_plant", "whole plant", "whole plant"),
        ("unknown_part", "unknown part", "unknown part"),
    ],
)
async def test_verified_part_vocabulary_is_never_silently_broadened(
    graph_service, token, phrase, stored
):
    service, graph = graph_service
    sid = (await service.create(uuid4())).correlation.session_id
    result = await service.submit(sid, ChatRequest(text=f"neem {phrase} compounds"), uuid4())
    assert result.status == "COMPLETE", result
    _, params = graph.read.call_args.args
    assert params["part"] == token
    assert stored in params["parts"]
    assert graph.read.await_count == 1
