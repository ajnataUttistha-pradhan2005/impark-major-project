from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from backend.contracts.response import FinalResponse
from backend.orchestrator.graph import RuntimeState, build_graph
from backend.state.models import TaskStatus
from backend.trace.recorder import TraceRecorder


async def run(harness, state):
    return (
        await build_graph(harness, InMemorySaver()).ainvoke(
            RuntimeState(domain=state),
            {
                "configurable": {"thread_id": str(uuid4())},
                "recursion_limit": 150,
            },
        )
    )["domain"]


async def test_terminal_state_cannot_restart(harness, state):
    state.termination.status = TaskStatus.COMPLETE
    final = await run(harness, state)
    assert final.termination.status == TaskStatus.COMPLETE
    assert final.execution.actions == []


async def test_existing_sufficient_context_skips_agents(harness, state, plant):
    state.context.active_plant = plant
    state.belief.confidence = 0.98
    final = await run(harness, state)
    assert final.termination.status == TaskStatus.COMPLETE
    assert final.execution.observations == []


async def test_forged_citation_fails_safely(harness, state, plant):
    class BadProvider:
        async def generate(self, request):
            return FinalResponse(text="untrusted-provider-text", citation_ids=[uuid4()])

    harness.llm = BadProvider()
    state.context.active_plant = plant
    state.belief.confidence = 0.98
    final = await run(harness, state)
    assert final.termination.status == TaskStatus.FAILED
    assert "untrusted-provider-text" not in final.response.text


async def test_trace_outage_does_not_change_runtime_outcome(harness, state, plant):
    class BrokenSink:
        async def write(self, event):
            raise OSError("fixture outage")

    state.context.active_plant = plant
    state.belief.confidence = 0.98
    healthy = await run(harness, state.model_copy(deep=True))
    recorder = TraceRecorder(BrokenSink(), capacity=2)
    harness.trace = recorder
    recorder.start()
    broken = await run(harness, state.model_copy(deep=True))
    await recorder.close()
    assert broken.termination == healthy.termination
    assert broken.response == healthy.response
    assert [a.action.name for a in broken.execution.actions] == [
        a.action.name for a in healthy.execution.actions
    ]
    assert recorder.write_failures > 0
