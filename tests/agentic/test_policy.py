from uuid import uuid4

import pytest

from backend.contracts.actions import Action, ActionName, ActionRecord
from backend.contracts.agents import ImageMetadata, ImageReference, QueryType
from backend.contracts.evidence import Contradiction, EvidenceGap
from backend.orchestrator.decision import DecisionEngine
from backend.orchestrator.policy import EligibilityPolicy
from backend.orchestrator.recovery import fingerprint
from backend.state.goals import Goal, Objective
from backend.state.models import TaskStatus


def test_state_change_changes_action(state, plant):
    engine = DecisionEngine(EligibilityPolicy())
    state.user_message = "fixture plant"
    state.belief.text_pending = True
    assert engine.decide_next_action(state).selected.name == ActionName.RESOLVE_TEXT_ENTITY
    state.belief.text_pending = False
    state.context.active_plant = plant
    state.belief.confidence = 0.98
    state.goal = Goal(objectives=[Objective(query_type=QueryType.GET_PHYTOCHEMICALS)])
    assert engine.decide_next_action(state).selected.name == ActionName.RETRIEVE_GRAPH
    assert ActionName.ANALYZE_IMAGE not in engine.policy.enumerate(state)
    state.evidence.gaps = [
        EvidenceGap(
            objective_id=state.goal.pending[0].objective_id, description="Missing relationship"
        )
    ]
    assert (
        engine.decide_next_action(state).selected.name
        == ActionName.RETRIEVE_ADDITIONAL_GRAPH_EVIDENCE
    )


def test_conflict_blocks_graph_and_triggers_reassessment(state, plant):
    policy = EligibilityPolicy()
    state.context.active_plant = plant
    state.belief.confidence = 0.98
    state.user_message = "fixture"
    state.goal = Goal(objectives=[Objective(query_type=QueryType.GET_PLANT_DETAILS)])
    state.evidence.contradictions = [Contradiction(entity_ids=[plant.plant_id], reason="fixture")]
    assert policy.enumerate(state) == [ActionName.RECONCILE_MODALITIES]
    state.evidence.contradictions[0].reconciled = True
    state.belief.requires_reassessment = True
    assert ActionName.REASSESS_ENTITY in policy.enumerate(state)
    assert ActionName.RETRIEVE_GRAPH not in policy.enumerate(state)


def test_image_eligible_only_with_input(state):
    policy = EligibilityPolicy()
    state.belief.image_pending = True
    assert ActionName.ANALYZE_IMAGE not in policy.enumerate(state)
    state.image = ImageReference(
        image_id=uuid4(),
        metadata=ImageMetadata(
            mime_type="image/png",
            size_bytes=50,
            width=10,
            height=10,
        ),
    )
    assert ActionName.ANALYZE_IMAGE in policy.enumerate(state)


@pytest.mark.parametrize(
    "status", [s for s in TaskStatus if s not in {TaskStatus.READY, TaskStatus.RUNNING}]
)
def test_stopped_states_have_no_actions(state, status):
    state.termination.status = status
    assert EligibilityPolicy().enumerate(state) == []


def test_equivalent_state_loop_guard(state):
    state.user_message = "fixture"
    state.belief.text_pending = True
    action = ActionName.RESOLVE_TEXT_ENTITY
    key = fingerprint(state, action)
    state.execution.actions = [
        ActionRecord(
            action=Action(name=action),
            fingerprint=key,
            status="executed",
            iteration=i,
        )
        for i in range(2)
    ]
    assert action not in EligibilityPolicy().enumerate(state)


def test_budget_preempts_capabilities(state):
    state.iteration = 8
    state.belief.text_pending = True
    state.user_message = "fixture"
    assert EligibilityPolicy().enumerate(state) == [ActionName.ABSTAIN]
