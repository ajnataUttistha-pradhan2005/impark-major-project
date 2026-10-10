import re

from backend.contracts.evidence import Modality
from backend.contracts.response import ClarificationResponse
from backend.state.models import ConversationState, Hypothesis, TaskStatus


def apply_clarification(state: ConversationState, reply: ClarificationResponse) -> None:
    pending = state.clarification
    if pending is None or reply.clarification_id != pending.clarification_id:
        raise ValueError("Clarification checkpoint mismatch")
    selected_id = reply.selected_plant_id
    ordinal = re.fullmatch(r"(?:option\s*)?([1-9])", reply.text.strip().casefold())
    if not selected_id and ordinal and int(ordinal.group(1)) <= len(pending.candidates):
        selected_id = pending.candidates[int(ordinal.group(1)) - 1].plant_id
    if selected_id:
        if state.session.locked_plant_id not in {None, selected_id}:
            raise ValueError("One plant per session")
        selected = next((c for c in pending.candidates if c.plant_id == selected_id), None)
        if selected is None:
            raise ValueError("Selection is not an offered candidate")
        selected = selected.model_copy(update={"confidence": 1.0, "match_method": "user_selection"})
        state.belief.hypotheses = [Hypothesis(candidate=selected, modality=Modality.TEXT)]
        state.belief.confidence = 1.0
        state.belief.text_pending = False
        state.belief.requires_reassessment = False
        state.evidence.contradictions = []
    else:
        state.user_message = reply.text
        state.belief.text_pending = True
    state.clarification = None
    state.termination.status = TaskStatus.RUNNING
