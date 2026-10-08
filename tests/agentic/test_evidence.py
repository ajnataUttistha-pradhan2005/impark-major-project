from backend.contracts.actions import Action, ActionName, Capability
from backend.contracts.agents import GraphAgentOutput, Observation, QueryType
from backend.contracts.evidence import (
    Contradiction,
    Evidence,
    EvidenceClass,
    EvidenceGap,
    Modality,
    Provenance,
)
from backend.evidence.context_builder import build_response_context
from backend.evidence.evaluator import evaluate_observation
from backend.state.goals import Goal, Objective


def graph_observation(state, harness, payload):
    return Observation(
        invocation=harness.execution.invocation(state, Action(name=ActionName.RETRIEVE_GRAPH)),
        component=Capability.GRAPH,
        payload=payload,
    )


def test_graph_contradiction_weakens_identity(state, plant, harness):
    state.context.active_plant = plant
    state.belief.confidence = 0.98
    state.user_message = "fixture"
    state.goal = Goal(objectives=[Objective(query_type=QueryType.GET_PLANT_DETAILS)])
    evaluate_observation(
        state,
        graph_observation(
            state,
            harness,
            GraphAgentOutput(
                placeholder=False,
                contradictions=[
                    Contradiction(
                        entity_ids=[plant.plant_id],
                        reason="Explicit contradictory fixture relation",
                    )
                ],
            ),
        ),
    )
    assert state.belief.confidence < 0.80
    assert state.belief.requires_reassessment
    assert ActionName.RETRIEVE_GRAPH not in harness.decision.policy.enumerate(state)


def test_empty_graph_does_not_falsify_identity(state, plant, harness):
    state.context.active_plant = plant
    state.belief.confidence = 0.98
    evaluate_observation(
        state, graph_observation(state, harness, GraphAgentOutput(placeholder=False))
    )
    assert state.belief.confidence == 0.98
    assert not state.evidence.contradictions


def test_evidence_preserved_in_context_and_not_mutable_alias(state, harness):
    evidence = Evidence(
        modality=Modality.GRAPH,
        claim="Synthetic traditional-use record",
        evidence_type=EvidenceClass.TRADITIONAL,
        confidence=0.8,
        provenance=Provenance(
            source_id="fixture:source", source_type="fixture", reference="Synthetic test only"
        ),
    )
    evaluate_observation(
        state,
        graph_observation(
            state,
            harness,
            GraphAgentOutput(
                placeholder=False,
                evidence=[evidence],
            ),
        ),
    )
    state.termination.ready_for_response = True
    context = build_response_context(state)
    assert context.graph_evidence[0].evidence_type == EvidenceClass.TRADITIONAL
    context.graph_evidence.clear()
    assert len(state.evidence.graph) == 1


def test_gap_blocks_objective_completion(state, harness):
    objective = state.goal.pending[0]
    evaluate_observation(
        state,
        graph_observation(
            state,
            harness,
            GraphAgentOutput(
                placeholder=False,
                completed_objectives=[objective.objective_id],
                gaps=[
                    EvidenceGap(objective_id=objective.objective_id, description="Missing source")
                ],
            ),
        ),
    )
    assert state.goal.pending
