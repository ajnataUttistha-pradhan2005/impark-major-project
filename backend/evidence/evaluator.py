from backend.contracts.agents import GraphAgentOutput, ImageAgentResult, Observation, TextResult
from backend.contracts.evidence import Contradiction, Modality
from backend.state.goals import ObjectiveStatus
from backend.state.models import ConversationState, Hypothesis


def evaluate_observation(state: ConversationState, observation: Observation) -> None:
    """Harness-owned reducer. An empty retrieval never means a claim is false."""
    payload = observation.payload
    if isinstance(payload, (TextResult, ImageAgentResult)):
        modality = Modality.TEXT if isinstance(payload, TextResult) else Modality.IMAGE
        state.belief.hypotheses = [h for h in state.belief.hypotheses if h.modality != modality] + [
            Hypothesis(candidate=c, modality=modality) for c in payload.candidates
        ]
        if modality == Modality.TEXT:
            state.belief.text_pending = False
            state.belief.requires_reassessment = False
        else:
            state.belief.image_pending = False
        top_by_modality = []
        for source in (Modality.TEXT, Modality.IMAGE):
            candidates = [h.candidate for h in state.belief.hypotheses if h.modality == source]
            if candidates:
                top_by_modality.append(max(candidates, key=lambda c: c.confidence).plant_id)
        if len(set(top_by_modality)) > 1 and not state.evidence.contradictions:
            state.evidence.contradictions.append(
                Contradiction(
                    entity_ids=top_by_modality, reason="Text/image candidate disagreement"
                )
            )
            state.belief.requires_reassessment = True
        state.belief.confidence = max(
            (h.candidate.confidence for h in state.belief.hypotheses if not h.weakened), default=0
        )
    elif isinstance(payload, GraphAgentOutput):
        if payload.placeholder:
            # A placeholder is neither evidence nor an objective completion.
            return
        known = {e.evidence_id for e in state.evidence.all_evidence()}
        for evidence in payload.evidence:
            if evidence.evidence_id not in known:
                getattr(state.evidence, evidence.modality.value).append(evidence)
                known.add(evidence.evidence_id)
        state.evidence.gaps = payload.gaps
        state.evidence.contradictions.extend(payload.contradictions)
        if payload.contradictions:
            state.belief.requires_reassessment = True
            state.belief.confidence = min(state.belief.confidence, 0.79)
            for hypothesis in state.belief.hypotheses:
                if any(
                    hypothesis.candidate.plant_id in c.entity_ids for c in payload.contradictions
                ):
                    hypothesis.weakened = True
        for objective in state.goal.objectives:
            if (
                objective.objective_id in payload.completed_objectives
                and payload.evidence
                and not payload.contradictions
                and not any(g.objective_id == objective.objective_id for g in payload.gaps)
            ):
                objective.status = ObjectiveStatus.COMPLETE
