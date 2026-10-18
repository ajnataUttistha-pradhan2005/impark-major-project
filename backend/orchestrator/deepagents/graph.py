"""LangGraph checkpoint/interrupt adapter preserving the public session schema."""

from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend.contracts.response import ClarificationResponse
from backend.orchestrator.deepagents.clarification import apply_clarification
from backend.orchestrator.deepagents.runtime import DeepAgentRuntime
from backend.state.models import ConversationState, TaskStatus


class RuntimeState(TypedDict):
    domain: ConversationState


def build_deep_graph(runtime: DeepAgentRuntime, checkpointer: BaseCheckpointSaver):
    graph = StateGraph(RuntimeState)

    async def run(value: RuntimeState) -> RuntimeState:
        state = ConversationState.model_validate(value["domain"])
        return {"domain": await runtime.run(state)}

    async def clarify(value: RuntimeState) -> RuntimeState:
        state = ConversationState.model_validate(value["domain"])
        assert state.clarification is not None
        raw = interrupt(state.clarification.model_dump(mode="json"))
        from backend.contracts.agents import ImageReference

        payload = dict(raw)
        replacement_data = payload.pop("_image", None)
        replacement = ImageReference.model_validate(replacement_data) if replacement_data else None
        apply_clarification(state, ClarificationResponse.model_validate(payload), replacement)
        return {"domain": state}

    graph.add_node("deep_orchestrator", run)
    graph.add_node("clarification", clarify)
    graph.add_edge(START, "deep_orchestrator")
    graph.add_conditional_edges(
        "deep_orchestrator",
        lambda value: (
            "clarification"
            if value["domain"].termination.status == TaskStatus.WAITING_USER
            else END
        ),
        ["clarification", END],
    )
    graph.add_edge("clarification", "deep_orchestrator")
    return graph.compile(checkpointer=checkpointer)
