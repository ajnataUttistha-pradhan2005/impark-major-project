"""Offline synthetic capability benchmark; optional real PostgreSQL checkpoints."""

import argparse
import asyncio
import json
from contextlib import AsyncExitStack
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from backend.agents.image.agent import ImageAgent
from backend.contracts.actions import Capability
from backend.contracts.agents import (
    CandidatePlant,
    GraphAgentInput,
    GraphAgentOutput,
    Observation,
    QueryType,
    TextAgentInput,
    TextResult,
)
from backend.contracts.evidence import Evidence, Modality, Provenance
from backend.database.postgres.checkpoints import checkpoints
from backend.database.search_config import SearchSettings
from backend.llm.grounded import GroundedResponseProvider
from backend.orchestrator.decision import DecisionEngine
from backend.orchestrator.execution import ExecutionManager
from backend.orchestrator.graph import RuntimeState, build_graph
from backend.orchestrator.orchestrator import Harness
from backend.orchestrator.policy import EligibilityPolicy
from backend.runtime import loop_factory
from backend.state.models import ConversationState
from backend.trace.recorder import MemoryTraceSink, TraceRecorder


class SyntheticText:
    async def execute(self, request: TextAgentInput) -> Observation:
        return Observation(
            invocation=request.invocation,
            component=Capability.TEXT,
            payload=TextResult(
                placeholder=False,
                candidates=[
                    CandidatePlant(
                        plant_id="benchmark:plant", label="Synthetic plant", confidence=0.99
                    )
                ],
                query_types=[QueryType.GET_PLANT_DETAILS],
            ),
        )


class SyntheticGraph:
    async def execute(self, request: GraphAgentInput) -> Observation:
        return Observation(
            invocation=request.invocation,
            component=Capability.GRAPH,
            payload=GraphAgentOutput(
                placeholder=False,
                completed_objectives=request.objective_ids,
                evidence=[
                    Evidence(
                        modality=Modality.GRAPH,
                        claim="Synthetic benchmark fact",
                        confidence=0.8,
                        provenance=Provenance(
                            source_id="benchmark", source_type="fixture", reference="Synthetic only"
                        ),
                    )
                ],
            ),
        )


async def benchmark(postgres: bool, runs: int, output: str) -> None:
    async with AsyncExitStack() as stack:
        saver = (
            await stack.enter_async_context(checkpoints(SearchSettings()))
            if postgres
            else (InMemorySaver())
        )
        recorder = TraceRecorder(MemoryTraceSink())
        recorder.start()
        harness = Harness(
            DecisionEngine(EligibilityPolicy()),
            ExecutionManager(SyntheticText(), ImageAgent(), SyntheticGraph()),
            GroundedResponseProvider(),
            recorder,
        )
        graph = build_graph(harness, saver)
        latencies = []
        try:
            for _ in range(runs):
                state = ConversationState.new()
                state.correlation.run_id = uuid4()
                state.user_message = "synthetic details"
                state.belief.text_pending = True
                thread = str(state.correlation.run_id)
                try:
                    start = perf_counter()
                    result = await graph.ainvoke(
                        RuntimeState(domain=state),
                        {"configurable": {"thread_id": thread}, "recursion_limit": 150},
                    )
                    latencies.append(round((perf_counter() - start) * 1000, 3))
                    assert result["domain"].termination.status == "COMPLETE"
                    assert result["domain"].response.citation_ids
                finally:
                    await saver.adelete_thread(thread)
        finally:
            await recorder.close()
        report = {
            "synthetic": True,
            "postgres_checkpoints": postgres,
            "runs": runs,
            "latency_ms": latencies,
            "median_ms": median(latencies),
            "max_ms": max(latencies),
            "trace_dropped": recorder.dropped,
            "trace_write_failures": recorder.write_failures,
        }
        await asyncio.to_thread(
            Path(output).write_text, json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true")
    parser.add_argument("--runs", type=int, choices=range(1, 51), default=5)
    parser.add_argument("--output", default="data/evaluation/harness_performance.json")
    args = parser.parse_args()
    asyncio.run(benchmark(args.postgres, args.runs, args.output), loop_factory=loop_factory)
