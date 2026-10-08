from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from backend.contracts.actions import ActionName, Capability
from backend.contracts.agents import GraphAgentOutput, Observation, QueryType, TextResult
from backend.contracts.evidence import Evidence, EvidenceClass, EvidenceGap, Modality, Provenance
from backend.orchestrator.graph import RuntimeState, build_graph
from backend.state.goals import Goal, Objective
from backend.state.models import TaskStatus


async def test_graph_gap_causes_additional_retrieval_then_early_completion(harness, state, plant):
    class FixtureText:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(candidates=[plant], placeholder=False),
            )

    class FixtureGraph:
        calls = 0

        async def execute(self, request):
            self.calls += 1
            if self.calls == 1:
                payload = GraphAgentOutput(
                    placeholder=False,
                    gaps=[
                        EvidenceGap(
                            objective_id=request.objective_ids[0],
                            description="Fixture provenance gap",
                        )
                    ],
                )
            else:
                assert request.evidence_gaps
                payload = GraphAgentOutput(
                    placeholder=False,
                    completed_objectives=request.objective_ids,
                    evidence=[
                        Evidence(
                            modality=Modality.GRAPH,
                            confidence=0.8,
                            claim="Synthetic fixture relation",
                            evidence_type=EvidenceClass.TRADITIONAL,
                            provenance=Provenance(
                                source_id="fixture:source",
                                source_type="fixture",
                                reference="Synthetic only",
                            ),
                        )
                    ],
                )
            return Observation(
                invocation=request.invocation, component=Capability.GRAPH, payload=payload
            )

    graph_agent = FixtureGraph()
    harness.execution.text = FixtureText()
    harness.execution.graph = graph_agent
    state.user_message = "fixture"
    state.belief.text_pending = True
    state.goal = Goal(objectives=[Objective(query_type=QueryType.GET_PHYTOCHEMICALS)])
    final = (
        await build_graph(harness, InMemorySaver()).ainvoke(
            RuntimeState(domain=state),
            {
                "configurable": {"thread_id": str(uuid4())},
                "recursion_limit": 150,
            },
        )
    )["domain"]
    assert graph_agent.calls == 2
    assert final.termination.status == TaskStatus.COMPLETE
    assert not final.goal.pending
    actions = [r.action.name for r in final.execution.actions]
    assert ActionName.RETRIEVE_ADDITIONAL_GRAPH_EVIDENCE in actions
    assert ActionName.ANALYZE_IMAGE not in actions
    assert final.response_context.graph_evidence[0].evidence_type == EvidenceClass.TRADITIONAL
