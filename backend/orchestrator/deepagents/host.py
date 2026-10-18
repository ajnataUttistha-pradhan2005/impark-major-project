"""Specialist dependencies and non-blocking trace emission for the Deep Agents path."""

from backend.agents.common.services import SpecialistServices
from backend.services.live import publish
from backend.state.models import ConversationState
from backend.trace.instrumentation import emit_state
from backend.trace.models import EventType
from backend.trace.recorder import TraceRecorder


class AgentHost:
    def __init__(self, execution: SpecialistServices, trace: TraceRecorder) -> None:
        self.execution = execution
        self.trace = trace

    def emit(self, state: ConversationState, event: EventType) -> None:
        emit_state(self.trace, state, event)
        if event in {
            EventType.TURN_STARTED,
            EventType.AGENT_INVOCATION_STARTED,
            EventType.CLARIFICATION_REQUESTED,
            EventType.RESPONSE_CONTEXT_BUILT,
        }:
            publish(
                "progress",
                {
                    "stage": event.value,
                    "mode": state.session.mode.value,
                    "run_id": str(state.correlation.run_id),
                },
            )
