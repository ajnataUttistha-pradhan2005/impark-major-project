from backend.orchestrator.policy import EligibilityPolicy
from backend.state.models import ConversationState, TaskStatus


def check_termination(state: ConversationState, policy: EligibilityPolicy) -> None:
    if state.termination.terminal or state.termination.status == TaskStatus.WAITING_USER:
        return
    if state.termination.ready_for_response:
        return
    if policy.resolved(state) and not state.goal.pending:
        state.termination.ready_for_response = True
        state.termination.reason = (
            TaskStatus.EVIDENCE_UNAVAILABLE
            if state.evidence.gaps or state.evidence.contradictions
            else "Objectives satisfied"
        )
    elif state.iteration >= state.budgets.max_iterations:
        state.termination.ready_for_response = True
        state.termination.reason = TaskStatus.MAX_ITERATIONS_REACHED
