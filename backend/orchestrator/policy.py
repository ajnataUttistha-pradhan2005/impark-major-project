from backend.contracts.actions import ActionName
from backend.orchestrator.recovery import can_retry, pending_failure, within_action_budget
from backend.state.models import ConversationState, TaskStatus


class EligibilityPolicy:
    def __init__(self, threshold: float = 0.95) -> None:
        self.threshold = threshold

    def resolved(self, state: ConversationState) -> bool:
        return (
            state.context.active_plant is not None
            and state.belief.confidence >= self.threshold
            and not state.evidence.contradictions
            and not state.belief.requires_reassessment
            and not state.belief.text_pending
            and not state.belief.image_pending
        )

    def enumerate(self, state: ConversationState) -> list[ActionName]:
        if state.termination.terminal or state.termination.status == TaskStatus.WAITING_USER:
            return []
        if state.response is not None:
            return [ActionName.COMPLETE]
        if state.termination.ready_for_response:
            return [ActionName.GENERATE_RESPONSE]
        if state.iteration >= state.budgets.max_iterations:
            return [ActionName.ABSTAIN]
        result: list[ActionName] = []
        failure = pending_failure(state)
        if failure is not None and can_retry(state, failure):
            return [ActionName.RETRY_ACTION]
        if state.belief.text_pending and state.user_message:
            result.append(ActionName.RESOLVE_TEXT_ENTITY)
        if state.belief.image_pending and state.image is not None:
            result.append(ActionName.ANALYZE_IMAGE)
        if any(not c.reconciled for c in state.evidence.contradictions):
            result.append(ActionName.RECONCILE_MODALITIES)
        elif state.belief.requires_reassessment and state.user_message:
            result.append(ActionName.REASSESS_ENTITY)
        candidates = [h.candidate for h in state.belief.hypotheses if not h.weakened]
        confident = [c for c in candidates if c.confidence >= self.threshold]
        if (
            confident
            and len({c.plant_id for c in confident}) == 1
            and not state.evidence.contradictions
            and not state.belief.text_pending
            and not state.belief.image_pending
            and not state.belief.requires_reassessment
            and state.context.active_plant != confident[0]
        ):
            result.append(ActionName.UPDATE_CONTEXT)
        graph_pending = any(o.query_type is not None for o in state.goal.pending)
        if self.resolved(state) and graph_pending:
            result.append(
                ActionName.RETRIEVE_ADDITIONAL_GRAPH_EVIDENCE
                if state.evidence.gaps
                else ActionName.RETRIEVE_GRAPH
            )
        failed_names = {f.invocation.action.name for f in state.execution.failures}
        result = [a for a in result if within_action_budget(state, a) and a not in failed_names]
        if not result:
            if self.resolved(state) and not state.goal.pending:
                return [ActionName.GENERATE_RESPONSE]
            if not self.resolved(state) and (
                state.clarification_count < state.budgets.max_clarifications
            ):
                return [ActionName.ASK_CLARIFICATION]
            return [ActionName.ABSTAIN]
        return result
