from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from backend.api.schemas.chat import ChatRequest
from backend.contracts.actions import ActionName, Capability
from backend.contracts.agents import Failure, FailureType, Observation, TextResult
from backend.orchestrator.graph import RuntimeState, build_graph
from backend.state.models import TaskStatus


async def test_real_interrupt_resume_preserves_lineage(service):
    created = await service.create(uuid4())
    session_id = created.correlation.session_id
    first = await service.submit(session_id, ChatRequest(text="unknown"), uuid4())
    assert first.status == TaskStatus.WAITING_USER
    second = await service.submit(session_id, ChatRequest(text="still unknown"), uuid4())
    assert second.correlation.run_id == first.correlation.run_id
    assert second.correlation.turn_id == first.correlation.turn_id
    third = await service.submit(session_id, ChatRequest(text="unknown again"), uuid4())
    assert third.status == TaskStatus.EVIDENCE_UNAVAILABLE
    assert third.response.placeholder
    assert len(await service.history(session_id)) == 1


async def test_resolved_fixture_skips_image_and_establishes_context(state, plant, harness):
    class FixtureText:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(candidates=[plant], placeholder=False),
            )

    harness.execution.text = FixtureText()
    state.user_message = "fixture"
    state.belief.text_pending = True
    graph = build_graph(harness, InMemorySaver())
    result = await graph.ainvoke(
        RuntimeState(domain=state),
        {
            "configurable": {"thread_id": str(uuid4())},
            "recursion_limit": 150,
        },
    )
    final = result["domain"]
    assert final.termination.status == TaskStatus.COMPLETE
    assert final.context.active_plant.plant_id == plant.plant_id
    assert final.session.mode == "conversation"
    assert ActionName.ANALYZE_IMAGE not in [r.action.name for r in final.execution.actions]


async def test_transient_retry_is_bounded(state, harness):
    class FailingText:
        calls = 0

        async def execute(self, request):
            self.calls += 1
            return Failure(
                invocation=request.invocation,
                error_type=FailureType.TRANSIENT,
                reason="fixture unavailable",
                retryable=True,
            )

    agent = FailingText()
    harness.execution.text = agent
    state.budgets.max_clarifications = 0
    state.user_message = "fixture"
    state.belief.text_pending = True
    graph = build_graph(harness, InMemorySaver())
    result = await graph.ainvoke(
        RuntimeState(domain=state),
        {
            "configurable": {"thread_id": str(uuid4())},
            "recursion_limit": 150,
        },
    )
    assert agent.calls == 3
    final = result["domain"]
    assert final.execution.retry_counts[ActionName.RESOLVE_TEXT_ENTITY] == 2
    assert final.termination.status == TaskStatus.EVIDENCE_UNAVAILABLE
    assert final.iteration <= 8


async def test_new_input_does_not_inherit_previous_identification(service, plant):
    from backend.contracts.evidence import Modality
    from backend.state.models import Hypothesis

    created = await service.create(uuid4())
    session_id = created.correlation.session_id
    stored = await service.load(session_id)
    stored.context.active_plant = plant
    stored.belief.confidence = 0.98
    stored.belief.hypotheses = [Hypothesis(candidate=plant, modality=Modality.TEXT)]
    stored.termination.status = TaskStatus.COMPLETE
    await service.repository.save(stored)
    result = await service.submit(
        session_id, ChatRequest(text="a different unknown plant"), uuid4()
    )
    assert result.status == TaskStatus.SCOPE_REJECTED
    assert (await service.load(session_id)).belief.confidence == 0
