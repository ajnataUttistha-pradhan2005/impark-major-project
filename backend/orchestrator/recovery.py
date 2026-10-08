import hashlib
import json

from backend.contracts.actions import ActionName
from backend.contracts.agents import Failure
from backend.state.models import ConversationState


def pending_failure(state: ConversationState) -> Failure | None:
    return next(
        (
            f
            for f in reversed(state.execution.failures)
            if f.failure_id not in state.execution.handled_failures
        ),
        None,
    )


def can_retry(state: ConversationState, failure: Failure) -> bool:
    name = failure.invocation.action.name
    return (
        failure.retryable
        and state.execution.retry_counts.get(name, 0) < state.budgets.max_agent_retries
        and sum(r.action.name == name for r in state.execution.actions)
        < state.budgets.max_action_calls
    )


def fingerprint(state: ConversationState, name: ActionName) -> str:
    """Input plus relevant belief/evidence; execution counters cannot defeat the guard."""
    data = {
        "action": name,
        "text": state.user_message,
        "image": str(state.image.image_id) if state.image else None,
        "context": state.context.model_dump(mode="json"),
        "belief": state.belief.model_dump(mode="json"),
        "evidence": state.evidence.model_dump(mode="json"),
        "goal": state.goal.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def within_action_budget(state: ConversationState, name: ActionName) -> bool:
    records = [r for r in state.execution.actions if r.action.name == name]
    key = fingerprint(state, name)
    return (
        len(records) < state.budgets.max_action_calls
        and sum(r.fingerprint == key for r in records) < state.budgets.repeated_action_threshold
    )
