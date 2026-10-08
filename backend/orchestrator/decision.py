from backend.contracts.actions import Action, ActionCandidate, ActionName, Decision
from backend.orchestrator.actions import REGISTRY
from backend.orchestrator.policy import EligibilityPolicy
from backend.state.models import ConversationState


class DecisionEngine:
    def __init__(self, policy: EligibilityPolicy) -> None:
        self.policy = policy

    def candidates(self, state: ConversationState) -> list[ActionCandidate]:
        candidates = []
        for name in self.policy.enumerate(state):
            definition = REGISTRY[name]
            repetitions = sum(r.action.name == name for r in state.execution.actions)
            score = (
                0.45 * definition.goal_progress
                + 0.35 * definition.information_gain
                + 0.20 * definition.priority
                - definition.latency_cost
                - definition.token_cost
                - 0.1 * repetitions
            )
            if name in {ActionName.RECONCILE_MODALITIES, ActionName.REASSESS_ENTITY}:
                # State-derived expected progress for resolving a blocking contradiction.
                score += 0.45 * (1 - definition.goal_progress)
            candidates.append(
                ActionCandidate(
                    name=name,
                    score=score,
                    eligibility_reason=", ".join(definition.prerequisites),
                )
            )
        return candidates

    def decide_next_action(self, state: ConversationState) -> Decision:
        candidates = self.candidates(state)
        if not candidates:
            raise ValueError("No action is eligible in a stopped state")
        chosen = max(candidates, key=lambda c: c.score)
        return Decision(selected=Action(name=chosen.name), candidates=candidates)
