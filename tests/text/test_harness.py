from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.agents.text.agent import TextAgent
from backend.api.schemas.chat import ChatRequest
from backend.contracts.response import ClarificationResponse
from backend.llm.grounded import GroundedResponseProvider
from backend.orchestrator.graph import build_graph


async def test_discovery_confirmation_resume_and_followup(service, name_search):
    service.harness.execution.text = TextAgent(name_search)
    service.harness.llm = GroundedResponseProvider()
    created = await service.create(uuid4())
    sid = created.correlation.session_id
    waiting = await service.submit(sid, ChatRequest(text="tulasi"), uuid4())
    assert waiting.status == "WAITING_USER"
    assert waiting.mode == "discovery"
    offered = waiting.clarification.candidates[0]
    # Simulate process restart: checkpoint is lost, interrupted domain state remains.
    service.graph = build_graph(service.harness, InMemorySaver())
    reply = ClarificationResponse(
        clarification_id=waiting.clarification.clarification_id, selected_plant_id=offered.plant_id
    )
    done = await service.submit(sid, ChatRequest(text=reply.text), uuid4(), reply)
    assert done.status == "COMPLETE"
    assert done.mode == "conversation"
    assert done.correlation.run_id == waiting.correlation.run_id
    assert done.active_plant.plant_id == offered.plant_id


async def test_autocomplete_and_verified_selection(service, name_search):
    service.harness.execution.text = TextAgent(name_search)
    sid = (await service.create(uuid4())).correlation.session_id
    hints = await service.autocomplete("nee")
    assert hints.implemented
    assert (await service.get(sid)).mode == "discovery"
    done = await service.submit(
        sid, ChatRequest(selected_plant_id=hints.candidates[0].plant_id), uuid4()
    )
    assert done.mode == "conversation"


async def test_invalid_selection_is_rejected(service, name_search):
    from backend.services.errors import ServiceError

    service.harness.execution.text = TextAgent(name_search)
    sid = (await service.create(uuid4())).correlation.session_id
    with pytest.raises(ServiceError):
        await service.submit(sid, ChatRequest(selected_plant_id=uuid4()), uuid4())


async def test_no_stale_evidence_for_new_turn(service, name_search):
    service.harness.execution.text = TextAgent(name_search)
    sid = (await service.create(uuid4())).correlation.session_id
    await service.submit(sid, ChatRequest(text="neem"), uuid4())
    result = await service.submit(sid, ChatRequest(text="unknown xqzzy"), uuid4())
    assert result.status == "WAITING_USER"
    state = await service.load(sid)
    assert not state.evidence.all_evidence()
    assert state.belief.confidence < 0.95


async def test_intent_clarification_preserves_identity_and_lineage(service, name_search):
    service.harness.execution.text = TextAgent(name_search)
    sid = (await service.create(uuid4())).correlation.session_id
    waiting = await service.submit(sid, ChatRequest(text="neem weather forecast"), uuid4())
    assert waiting.status == "WAITING_USER"
    assert waiting.active_plant is not None
    reply = ClarificationResponse(
        clarification_id=waiting.clarification.clarification_id, text="uses"
    )
    result = await service.submit(sid, ChatRequest(text=reply.text), uuid4(), reply)
    assert result.correlation.run_id == waiting.correlation.run_id
    state = await service.load(sid)
    assert not state.belief.intent_pending
    assert state.context.active_plant.plant_id == waiting.active_plant.plant_id


async def test_part_clarification_resumes_with_single_scope(service, name_search):
    service.harness.execution.text = TextAgent(name_search)
    sid = (await service.create(uuid4())).correlation.session_id
    waiting = await service.submit(
        sid, ChatRequest(text="Compounds in neem leaves and roots"), uuid4()
    )
    assert waiting.status == "WAITING_USER"
    reply = ClarificationResponse(
        clarification_id=waiting.clarification.clarification_id, text="leaf"
    )
    await service.submit(sid, ChatRequest(text=reply.text), uuid4(), reply)
    state = await service.load(sid)
    assert not state.belief.intent_pending
    assert state.context.active_part == "leaf"
