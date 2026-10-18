from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.orchestrator.deepagents.graph import RuntimeState, build_deep_graph
from backend.state.models import ConversationState, TaskStatus


@pytest.mark.asyncio
async def test_deep_runtime_is_the_checkpointed_execution_path():
    class Runtime:
        calls = 0

        async def run(self, state: ConversationState) -> ConversationState:
            self.calls += 1
            state.termination.status = TaskStatus.COMPLETE
            return state

    runtime = Runtime()
    graph = build_deep_graph(runtime, InMemorySaver())
    state = ConversationState.new()
    config = {"configurable": {"thread_id": str(uuid4())}}
    result = await graph.ainvoke(RuntimeState(domain=state), config)
    assert runtime.calls == 1
    assert result["domain"].termination.status == TaskStatus.COMPLETE
    checkpoint = await graph.aget_state(config)
    assert checkpoint.values["domain"].termination.status == TaskStatus.COMPLETE
