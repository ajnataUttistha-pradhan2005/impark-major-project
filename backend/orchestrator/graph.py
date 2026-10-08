"""Actual cyclic LangGraph runtime, with typed state and checkpoint interrupts."""

from collections.abc import Awaitable, Callable
from typing import TypedDict

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from backend.contracts.actions import ActionName
from backend.contracts.response import ClarificationResponse
from backend.orchestrator.orchestrator import Harness
from backend.state.models import ConversationState, TaskStatus
from backend.trace.models import EventType


class RuntimeState(TypedDict):
    domain: ConversationState


def build_graph(
    harness: Harness,
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[RuntimeState, None, RuntimeState, RuntimeState]:
    graph = StateGraph(RuntimeState)

    def sync_node(
        operation: Callable[[ConversationState], None],
    ) -> Callable[[RuntimeState], Awaitable[RuntimeState]]:
        async def node(value: RuntimeState) -> RuntimeState:
            state = value["domain"].model_copy(deep=True)
            operation(state)
            return {"domain": state}

        return node

    async def dispatch(value: RuntimeState) -> RuntimeState:
        state = value["domain"].model_copy(deep=True)
        await harness.dispatch(state)
        return {"domain": state}

    async def generate(value: RuntimeState) -> RuntimeState:
        state = value["domain"].model_copy(deep=True)
        await harness.generate(state)
        return {"domain": state}

    async def clarify(value: RuntimeState) -> RuntimeState:
        state = value["domain"].model_copy(deep=True)
        assert state.clarification is not None
        raw = interrupt(state.clarification.model_dump(mode="json"))
        reply = ClarificationResponse.model_validate(raw)
        if reply.clarification_id != state.clarification.clarification_id:
            raise ValueError("Clarification does not match this checkpoint")
        state.user_message = reply.text
        state.belief.text_pending = True
        state.clarification = None
        state.termination.status = TaskStatus.RUNNING
        harness.emit(state, EventType.EXECUTION_RESUMED)
        return {"domain": state}

    operations = {
        "observe_turn": harness.observe,
        "assess_goal_and_state": harness.assess,
        "enumerate_actions": harness.enumerate_actions,
        "decide_next_action": harness.decide,
        "collect_observations": harness.collect,
        "evaluate_evidence": harness.evaluate,
        "update_state": harness.update,
        "termination_check": harness.terminate,
        "final_context": harness.context,
    }
    for name, operation in operations.items():
        graph.add_node(name, RunnableLambda(sync_node(operation)))
    graph.add_node("dispatch", RunnableLambda(dispatch))
    graph.add_node("clarification", RunnableLambda(clarify))
    graph.add_node("final_response", RunnableLambda(generate))
    # Persistence at this boundary is LangGraph checkpointing. Application repositories
    # save the completed/interrupted state in the service layer; no trace writes here.
    graph.add_node("persistence", lambda value: value)

    def route_start(value: RuntimeState) -> str:
        return "persistence" if value["domain"].termination.terminal else "observe_turn"

    graph.add_conditional_edges(START, route_start, ["persistence", "observe_turn"])
    graph.add_edge("observe_turn", "assess_goal_and_state")
    graph.add_edge("assess_goal_and_state", "enumerate_actions")
    graph.add_edge("enumerate_actions", "decide_next_action")

    def route_decision(value: RuntimeState) -> str:
        decision = value["domain"].last_decision
        assert decision is not None
        return (
            "final_context"
            if decision.selected.name == ActionName.GENERATE_RESPONSE
            else "dispatch"
        )

    graph.add_conditional_edges("decide_next_action", route_decision, ["final_context", "dispatch"])
    graph.add_edge("dispatch", "collect_observations")
    graph.add_edge("collect_observations", "evaluate_evidence")
    graph.add_edge("evaluate_evidence", "update_state")
    graph.add_edge("update_state", "termination_check")

    def route_termination(value: RuntimeState) -> str:
        state = value["domain"]
        if state.termination.terminal:
            return "persistence"
        if state.termination.status == TaskStatus.WAITING_USER:
            return "clarification"
        return "assess_goal_and_state"

    graph.add_conditional_edges(
        "termination_check",
        route_termination,
        ["persistence", "clarification", "assess_goal_and_state"],
    )
    graph.add_edge("clarification", "assess_goal_and_state")
    graph.add_edge("final_context", "final_response")
    graph.add_edge("final_response", "enumerate_actions")
    graph.add_edge("persistence", END)
    return graph.compile(checkpointer=checkpointer)
