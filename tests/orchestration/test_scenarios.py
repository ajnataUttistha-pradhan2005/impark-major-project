"""Deterministic scenario sweep across independent teammate capability implementations."""

import random
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.contracts.actions import ActionName, Capability
from backend.contracts.agents import (
    Failure,
    FailureType,
    GraphAgentOutput,
    ImageAgentResult,
    ImageMetadata,
    ImageQualityResult,
    ImageReference,
    Observation,
    QueryType,
    TextResult,
)
from backend.contracts.evidence import Evidence, EvidenceGap, Modality, Provenance
from backend.orchestrator.graph import RuntimeState, build_graph
from backend.state.goals import Objective


@pytest.mark.parametrize("seed", range(32))
async def test_multimodal_recovery_scenario_sweep(seed, state, harness, plant):
    rng = random.Random(seed)
    has_image = rng.choice([True, False])
    disagree = rng.choice([True, False])
    retry = rng.choice([True, False])
    gap = rng.choice([True, False])
    confidence = rng.choice([0.99, 0.79])
    text_plant = plant.model_copy(update={"confidence": confidence})
    image_plant = plant.model_copy(update={"plant_id": "fixture:B" if disagree else plant.plant_id})

    class Text:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(placeholder=False, candidates=[text_plant]),
            )

    class Image:
        async def execute(self, request):
            return Observation(
                invocation=request.invocation,
                component=Capability.IMAGE,
                payload=ImageAgentResult(
                    placeholder=False,
                    candidates=[image_plant],
                    quality=ImageQualityResult(checked=True, usable=True, is_plant=True),
                ),
            )

    class Graph:
        calls = 0

        async def execute(self, request):
            self.calls += 1
            if retry and self.calls == 1:
                return Failure(
                    invocation=request.invocation,
                    error_type=FailureType.TRANSIENT,
                    reason="synthetic transient",
                    retryable=True,
                )
            if gap:
                payload = GraphAgentOutput(
                    placeholder=False,
                    gaps=[
                        EvidenceGap(
                            objective_id=request.objective_ids[0], description="synthetic gap"
                        )
                    ],
                )
            else:
                payload = GraphAgentOutput(
                    placeholder=False,
                    completed_objectives=request.objective_ids,
                    evidence=[
                        Evidence(
                            modality=Modality.GRAPH,
                            claim="synthetic evidence",
                            confidence=0.8,
                            provenance=Provenance(
                                source_id="fixture", source_type="fixture", reference="fixture"
                            ),
                        )
                    ],
                )
            return Observation(
                invocation=request.invocation, component=Capability.GRAPH, payload=payload
            )

    graph = Graph()
    harness.execution.text = Text()
    harness.execution.image = Image()
    harness.execution.graph = graph
    state.user_message = "fixture"
    state.belief.text_pending = True
    state.belief.image_pending = has_image
    state.goal.objectives = [Objective(query_type=QueryType.GET_PHYTOCHEMICALS)]
    if has_image:
        state.image = ImageReference(
            image_id=uuid4(),
            metadata=ImageMetadata(mime_type="image/png", width=10, height=10, size_bytes=40),
        )
    final = (
        await build_graph(harness, InMemorySaver()).ainvoke(
            RuntimeState(domain=state),
            {"configurable": {"thread_id": str(uuid4())}, "recursion_limit": 150},
        )
    )["domain"]
    assert final.iteration <= 8
    assert final.termination.terminal or final.termination.status == "WAITING_USER"
    if has_image and disagree:
        assert graph.calls == 0
        assert final.termination.status != "COMPLETE"
    if final.termination.status == "COMPLETE":
        assert not gap
        assert final.evidence.graph
        assert not final.evidence.contradictions
    if not has_image:
        assert all(r.action.name != ActionName.ANALYZE_IMAGE for r in final.execution.actions)
