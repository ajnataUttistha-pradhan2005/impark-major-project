from backend.contracts.agents import GraphAgentOutput
from backend.contracts.response import ResponseContext
from backend.state.models import ConversationState


def build_response_context(state: ConversationState) -> ResponseContext:
    if not state.termination.ready_for_response:
        raise ValueError("Response requires an answerable or transparent outcome")
    return ResponseContext(
        intent=state.goal.intent,
        resolved_plant=state.context.active_plant if state.belief.identity_required else None,
        text_evidence=state.evidence.text,
        image_evidence=state.evidence.image,
        graph_evidence=state.evidence.graph,
        uncertainties=[g.description for g in state.evidence.gaps]
        + [
            message
            for o in state.execution.observations
            if isinstance(o.payload, GraphAgentOutput)
            for message in o.payload.limitations
        ]
        + [c.reason for c in state.evidence.contradictions]
        + (
            [state.termination.reason]
            if state.termination.reason and state.termination.reason != "Objectives satisfied"
            else []
        ),
        outcome=state.termination.reason or "Objectives satisfied",
    ).model_copy(deep=True)
