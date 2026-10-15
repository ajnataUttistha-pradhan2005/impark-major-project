from backend.contracts.agents import GraphAgentOutput, ImageAgentResult, Observation, TextResult
from backend.contracts.evidence import Contradiction, Modality
from backend.state.goals import Objective, ObjectiveStatus
from backend.state.models import ConversationState, Hypothesis


def evaluate_observation(state: ConversationState, observation: Observation) -> None:
    """Harness-owned reducer. An empty retrieval never means a claim is false."""
    payload = observation.payload
    if isinstance(payload, TextResult) and not payload.placeholder:
        state.belief.intent_pending = payload.intent_uncertain
        from backend.state.models import TaskStatus

        if payload.scope_rejected:
            state.termination.ready_for_response = True
            state.termination.reason = TaskStatus.SCOPE_REJECTED
            state.belief.text_pending = False
            return
        if payload.safety_abstention:
            state.termination.ready_for_response = True
            state.termination.reason = TaskStatus.SAFETY_ABSTENTION
        if payload.queries:
            state.belief.identity_required = True
            state.goal.intent = (
                payload.queries[0].query_type.value
                if len(payload.queries) == 1
                else "SCOPED_GRAPH_RETRIEVAL"
            )
            state.goal.objectives = [
                Objective(
                    description=q.query_type.value,
                    query_type=q.query_type,
                    parameters=q.parameters,
                    required_evidence=[Modality.GRAPH],
                )
                for q in payload.queries
            ]
        elif payload.query_types:
            state.goal.intent = payload.intent
            existing = {o.query_type for o in state.goal.objectives}
            state.goal.objectives.extend(
                Objective(description=q.value, query_type=q, required_evidence=[Modality.GRAPH])
                for q in payload.query_types
                if q not in existing
            )
        if payload.part:
            state.context.active_part = payload.part
    if isinstance(payload, (TextResult, ImageAgentResult)):
        modality = Modality.TEXT if isinstance(payload, TextResult) else Modality.IMAGE
        candidates = payload.candidates
        if isinstance(payload, ImageAgentResult):
            known = {e.evidence_id for e in state.evidence.image}
            state.evidence.image.extend(
                e.model_copy(deep=True) for e in payload.evidence if e.evidence_id not in known
            )
            if payload.quality.usable is False or payload.quality.is_plant is False:
                candidates = []
        locked = state.session.locked_plant_id or (
            state.context.active_plant.plant_id if state.context.active_plant else None
        )
        if locked and any(c.plant_id != locked and c.confidence >= 0.95 for c in candidates):
            from backend.state.models import TaskStatus

            state.termination.ready_for_response = True
            state.termination.reason = TaskStatus.SCOPE_REJECTED
            state.belief.text_pending = state.belief.image_pending = False
            return
        state.belief.hypotheses = [h for h in state.belief.hypotheses if h.modality != modality] + [
            Hypothesis(candidate=c.model_copy(deep=True), modality=modality) for c in candidates
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
                getattr(state.evidence, evidence.modality.value).append(
                    evidence.model_copy(deep=True)
                )
                known.add(evidence.evidence_id)
        updated_objectives = set(payload.completed_objectives) | {
            gap.objective_id for gap in payload.gaps
        }
        state.evidence.gaps = [
            gap for gap in state.evidence.gaps if gap.objective_id not in updated_objectives
        ] + payload.gaps
        state.evidence.contradictions.extend(payload.contradictions)
        state.context.citation_history = list(
            {
                e.evidence_id: e for e in [*state.context.citation_history, *payload.evidence]
            }.values()
        )[-100:]
        if any(c.affects_identity for c in payload.contradictions):
            state.belief.requires_reassessment = True
            state.belief.confidence = min(state.belief.confidence, 0.79)
            for hypothesis in state.belief.hypotheses:
                if any(
                    hypothesis.candidate.plant_id in c.entity_ids for c in payload.contradictions
                ):
                    hypothesis.weakened = True
        for objective in state.goal.objectives:
            if objective.objective_id in payload.completed_objectives and any(
                not c.affects_identity for c in payload.contradictions
            ):
                objective.status = ObjectiveStatus.UNAVAILABLE
            if any(
                g.objective_id == objective.objective_id and not g.recoverable for g in payload.gaps
            ):
                objective.status = ObjectiveStatus.UNAVAILABLE
            if (
                objective.objective_id in payload.completed_objectives
                and payload.evidence
                and not payload.contradictions
                and not any(g.objective_id == objective.objective_id for g in payload.gaps)
            ):
                objective.status = ObjectiveStatus.COMPLETE
