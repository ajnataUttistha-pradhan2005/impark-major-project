import asyncio
from uuid import uuid4

import pytest

from backend.api.schemas.chat import ChatRequest
from backend.contracts.actions import Action, ActionName, Capability
from backend.contracts.agents import (
    Failure,
    FailureType,
    GraphAgentOutput,
    ImageAgentResult,
    ImageMetadata,
    ImageQualityResult,
    ImageReference,
    Observation,
    QueryType,
    TextResult,
)
from backend.contracts.evidence import Modality
from backend.evidence.evaluator import evaluate_observation
from backend.orchestrator.policy import EligibilityPolicy
from backend.orchestrator.recovery import can_retry
from backend.services.errors import ServiceError
from backend.state.goals import Objective
from backend.state.models import Hypothesis


async def test_agent_cannot_mutate_state_or_forge_lineage(harness, state, plant):
    class MutatingText:
        async def execute(self, request):
            request.active_plant.label = "mutated"
            request.invocation.correlation.session_id = uuid4()
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(placeholder=False),
            )

    harness.execution.text = MutatingText()
    state.user_message = "fixture"
    state.context.active_plant = plant
    invocation = harness.execution.invocation(state, Action(name=ActionName.RESOLVE_TEXT_ENTITY))
    original = state.model_dump_json()
    result = await harness.execution.execute(state, invocation)
    assert isinstance(result, Failure)
    assert state.model_dump_json() == original


async def test_graph_cannot_complete_unrequested_objective(harness, state, plant):
    class ForgedGraph:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.GRAPH,
                payload=GraphAgentOutput(placeholder=False, completed_objectives=[uuid4()]),
            )

    harness.execution.graph = ForgedGraph()
    state.context.active_plant = plant
    state.goal.objectives = [Objective(query_type=QueryType.GET_PLANT_DETAILS)]
    result = await harness.execution.execute(
        state, harness.execution.invocation(state, Action(name=ActionName.RETRIEVE_GRAPH))
    )
    assert isinstance(result, Failure)
    assert result.reason == "Invalid objective scope"


@pytest.mark.parametrize(
    "kind",
    [
        FailureType.PERMANENT,
        FailureType.INVALID_INPUT,
        FailureType.POLICY_REJECTION,
        FailureType.UNSUPPORTED_OPERATION,
    ],
)
def test_nontransient_failure_cannot_force_retry(state, harness, kind):
    invocation = harness.execution.invocation(state, Action(name=ActionName.RESOLVE_TEXT_ENTITY))
    assert not can_retry(
        state, Failure(invocation=invocation, error_type=kind, reason="fixture", retryable=True)
    )


@pytest.mark.parametrize("quality", [{"usable": False}, {"is_plant": False}])
def test_bad_image_cannot_establish_identity(state, harness, plant, quality):
    invocation = harness.execution.invocation(state, Action(name=ActionName.ANALYZE_IMAGE))
    observation = Observation(
        invocation=invocation,
        component=Capability.IMAGE,
        payload=ImageAgentResult(
            placeholder=False,
            candidates=[plant],
            quality=ImageQualityResult(checked=True, **quality),
        ),
    )
    evaluate_observation(state, observation)
    assert not state.belief.hypotheses
    assert state.belief.confidence == 0


def test_new_identity_blocks_stale_graph_context(state, plant):
    state.context.active_plant = plant
    other = plant.model_copy(update={"plant_id": "fixture:B"})
    state.belief.hypotheses = [Hypothesis(candidate=other, modality=Modality.TEXT)]
    state.belief.confidence = 0.99
    state.goal.objectives = [Objective(query_type=QueryType.GET_PLANT_DETAILS)]
    actions = EligibilityPolicy().enumerate(state)
    assert ActionName.UPDATE_CONTEXT in actions
    assert ActionName.RETRIEVE_GRAPH not in actions


async def test_cancelled_turn_recovers_without_new_lineage(service, plant):
    started = asyncio.Event()

    class BlockingText:
        calls = 0

        async def execute(self, request):
            self.calls += 1
            if self.calls == 1:
                started.set()
                await asyncio.Event().wait()
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(placeholder=False, candidates=[plant]),
            )

    agent = BlockingText()
    service.harness.execution.text = agent
    sid = (await service.create(uuid4())).correlation.session_id
    task = asyncio.create_task(service.submit(sid, ChatRequest(text="fixture"), uuid4()))
    await asyncio.wait_for(started.wait(), 2)
    with pytest.raises(ServiceError):
        await service.submit(sid, ChatRequest(text="overlap"), uuid4())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    original = await service.load(sid)
    result = await service.recover(sid)
    assert result.status == "COMPLETE"
    assert result.correlation.run_id == original.correlation.run_id
    assert agent.calls == 2
    assert not service.locks


@pytest.mark.parametrize("delay", [0, 0.001, 0.005])
async def test_image_teammate_plugs_in_without_harness_changes(service, plant, delay):
    class FixtureImage:
        async def execute(self, request):
            await asyncio.sleep(delay)
            return Observation(
                invocation=request.invocation,
                component=Capability.IMAGE,
                payload=ImageAgentResult(
                    placeholder=False,
                    candidates=[plant],
                    quality=ImageQualityResult(checked=True, usable=True, is_plant=True),
                ),
            )

    service.harness.execution.image = FixtureImage()
    sid = (await service.create(uuid4())).correlation.session_id
    image = ImageReference(
        image_id=uuid4(),
        metadata=ImageMetadata(mime_type="image/png", size_bytes=50, width=10, height=10),
    )
    service.images[sid] = {image.image_id: image}
    result = await service.submit(sid, ChatRequest(image_id=image.image_id), uuid4())
    assert result.status == "COMPLETE"
    assert result.active_plant.plant_id == plant.plant_id


async def test_application_composition_accepts_typed_agent_override(plant):
    import httpx

    from backend.agents.common.bundle import AgentOverrides
    from backend.config.settings import Settings
    from backend.main import create_app

    class TeamText:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(placeholder=False, candidates=[plant]),
            )

    app = create_app(
        Settings(_env_file=None, enable_development_api=True),
        agents=AgentOverrides(text=TeamText()),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            sid = (await client.post("/dev/conversations")).json()["correlation"]["session_id"]
            result = await client.post(f"/dev/conversations/{sid}/turns", json={"text": "fixture"})
            assert result.status_code == 200
            assert result.json()["active_plant"]["plant_id"] == plant.plant_id


def test_successful_retry_does_not_block_later_graph_work(state, harness, plant):
    state.context.active_plant = plant
    state.belief.confidence = 0.99
    state.goal.objectives = [Objective(query_type=QueryType.GET_PLANT_DETAILS)]
    invocation = harness.execution.invocation(state, Action(name=ActionName.RETRIEVE_GRAPH))
    failure = Failure(
        invocation=invocation, error_type=FailureType.TRANSIENT, reason="fixture", retryable=True
    )
    state.execution.failures = [failure]
    state.execution.handled_failures = [failure.failure_id]
    assert ActionName.RETRIEVE_GRAPH in EligibilityPolicy().enumerate(state)
