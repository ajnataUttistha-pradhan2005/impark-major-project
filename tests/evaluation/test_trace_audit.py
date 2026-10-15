from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from backend.contracts.actions import Capability
from backend.contracts.agents import GraphAgentOutput, Observation, QueryType, TextResult
from backend.contracts.evidence import Evidence, Modality, Provenance
from backend.evaluation.trace_audit import audit_run
from backend.llm.grounded import GroundedResponseProvider
from backend.orchestrator.graph import RuntimeState, build_graph
from backend.trace.models import EventType


async def test_trace_audit_accepts_state_derived_complete_and_clarification_paths(
    state, harness, plant
):
    class Text:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(
                    placeholder=False,
                    candidates=[plant],
                    query_types=[QueryType.GET_PLANT_DETAILS],
                ),
            )

    class Graph:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.GRAPH,
                payload=GraphAgentOutput(
                    placeholder=False,
                    completed_objectives=request.objective_ids,
                    evidence=[
                        Evidence(
                            modality=Modality.GRAPH,
                            claim="Synthetic fact",
                            confidence=0.8,
                            provenance=Provenance(
                                source_id="fixture", source_type="fixture", reference="fixture"
                            ),
                        )
                    ],
                ),
            )

    harness.execution.text = Text()
    harness.execution.graph = Graph()
    harness.llm = GroundedResponseProvider()
    harness.trace.start()
    state.user_message = "synthetic plant details"
    state.belief.text_pending = True
    result = await build_graph(harness, InMemorySaver()).ainvoke(
        RuntimeState(domain=state),
        {"configurable": {"thread_id": str(state.correlation.run_id)}, "recursion_limit": 150},
    )
    await harness.trace.close()
    final = result["domain"]
    assert final.termination.status == "COMPLETE"
    events = harness.trace.sink.events
    report = audit_run(
        events,
        state.correlation.run_id,
        expected_outcome=final.termination.status,
        dropped=harness.trace.dropped,
        write_failures=harness.trace.write_failures,
    )
    assert report.passed, report.issues
    assert report.decision_count >= 4 and report.invocation_count == 2

    # The evaluator detects a forged action without assuming an exact action sequence.
    decision = next(event for event in events if event.event_type == EventType.DECISION_MADE)
    decision.action = None
    assert not audit_run(events, state.correlation.run_id, expected_outcome="COMPLETE").passed
    assert not audit_run(
        events, state.correlation.run_id, expected_outcome="COMPLETE", dropped=1
    ).passed


async def test_trace_audit_recognizes_clarification_without_response(state, harness):
    harness.trace.start()
    state.user_message = "unknown fixture"
    state.belief.text_pending = True
    result = await build_graph(harness, InMemorySaver()).ainvoke(
        RuntimeState(domain=state),
        {"configurable": {"thread_id": str(uuid4())}, "recursion_limit": 150},
    )
    await harness.trace.close()
    assert result["domain"].termination.status == "WAITING_USER"
    report = audit_run(
        harness.trace.sink.events,
        state.correlation.run_id,
        expected_outcome="WAITING_USER",
    )
    assert report.passed, report.issues
