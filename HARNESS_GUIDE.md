# Harness operation and teammate integration

## Runtime guarantees

There are exactly three specialized capabilities. The harness owns goals, belief, evidence,
decisions, budgets and transitions; agents return `Observation | Failure`. A state-derived
eligible action is scored using the documented deterministic heuristic. The runtime remains a
bounded LangGraph cycle, with eight iterations, two retries and two clarification attempts by
default. Invocation and graph-query deadlines remain independent of trace persistence.

Pure assessment/decision operations now share a `plan` checkpoint, and collection/evaluation/
update/termination share a `reduce` checkpoint. All original domain events remain emitted.
Agent dispatch is still a separate durable node. Compatibility nodes permit resuming checkpoints
from the earlier granular graph. No agent receives global state or chooses its own next action.

The execution boundary deep-copies inputs, revalidates returned models, rejects forged lineage,
wrong capabilities, foreign objective completion and graph evidence with another modality.
Permanent/invalid/policy failures cannot demand retries. A successful retry no longer blocks later
work. Text/image disagreement blocks graph retrieval; explicit image-quality rejection discards
its candidates. Graph gaps remain scoped to their objectives. Stale plant context cannot satisfy
a newly resolved identity. Concurrent turns for the same session receive HTTP 409.

## Durable operation

Install the refreshed dependencies and explicitly migrate:

```powershell
.venv\Scripts\python.exe -m pip install -e '.[dev]'
docker start neo4j-dev impark-major-project-postgres-1 impark-major-project-qdrant-1
.venv\Scripts\python.exe -m backend.database.search_admin migrate
.venv\Scripts\python.exe -m backend
```

`python -m backend` selects a psycopg-compatible asyncio loop on Windows and binds to localhost
port 8000. The same code works on Linux. A direct Uvicorn invocation on Windows must use
`--loop backend.runtime:loop_factory` with a Uvicorn version supporting custom loop factories.

With text search enabled, the official `AsyncPostgresSaver` persists LangGraph checkpoints in
the configured PostgreSQL database. Startup checks readiness but does not migrate. Serialization
explicitly allow-lists application contracts and disables pickle fallback. A dedicated connection
is reused and closed with application lifespan; statement and connection timeouts are configured.
The existing application pool remains responsible for sessions/history and background traces.

A new turn is persisted as RUNNING before executing. After cancellation/process interruption,
POST `/dev/conversations/{session_id}/resume` to continue its checkpoint under the same run ID.
New turns are rejected while that interrupted run awaits recovery. Waiting-user clarification
still uses `/clarifications` with the returned clarification ID. A reply interrupted before its
checkpoint is saved may be requested again; it is never guessed. Completed nodes are recovered;
an unfinished node can execute again. This is **at-least-once execution**, not exactly-once.
Agents must therefore remain read-only or explicitly idempotent. External side effects are not
authorized by a replay. No background startup replay is performed automatically.

Use one API worker for this academic deployment: session admission locks are process-local.
Durable checkpoints do not by themselves provide multi-process session ownership. Checkpoint,
session and trace retention need an explicit administrative policy before long-running deployment.

## Plugging in teammates' agents

Implement the existing generic interface in `backend/agents/common/contracts.py`:

```python
async def execute(self, request: ImageAgentInput) -> Observation | Failure:
    ...
```

Use `TextAgentInput`, `ImageAgentInput`, or `GraphAgentInput` as appropriate. Preserve the exact
request invocation in every result. Return the matching typed payload with `placeholder=False`
only when real work was performed. Do not mutate the request, invent evidence, access harness
state, bypass graph validation, or upgrade evidence classes. CPU/GPU inference belongs off the
event loop; cancellation must not spawn an unbounded queue of native workers.

At the composition boundary:

```python
from backend.agents.common.bundle import AgentOverrides
from backend.main import create_app

app = create_app(agents=AgentOverrides(image=your_image_agent, graph=your_graph_agent))
```

Unspecified capabilities use existing defaults. Overrides are installed after store initialization.
Agents/providers own their declared inference lifecycle; adapt the composition root to inject
the existing shared database clients rather than opening a driver per invocation.

The Image Agent receives an opaque validated image reference and invocation/session identity.
It should report `quality.checked`, `quality.usable`, `quality.is_plant`, ranked candidates,
alternatives and part observations. **Pixel/blob persistence is still the Image Agent milestone:**
the current upload endpoint validates bytes and stores reference metadata, not durable image bytes.
Teammates must add a session-scoped blob repository before real inference or image replay can work.
The harness compatibility tests use synthetic image results and do not claim real image accuracy.

The Graph Agent receives a validated `GraphQuery`, requested objective IDs and evidence gaps.
Complete only the requested objective and return graph evidence/provenance. Return gaps for
missing data and contradictions only when supported, rather than treating absence as refutation.
Retryable failures should be transient, timeout or dependency-unavailable failures. Graph query
text is selected by a repository, never supplied by user/model text.

## Validation and performance

```powershell
$env:SEARCH_RUN_INTEGRATION='1'
$env:NEO4J_RUN_INTEGRATION='1'
$env:NEO4J_TEST_WRITES='1'
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m backend.evaluation.harness_benchmark --postgres --runs 5
.venv\Scripts\python.exe -m backend.evaluation.text_discovery --semantic
```

The benchmark uses synthetic capability outputs and deletes only its own temporary checkpoint
threads. Five local runs measured median harness latency **182.019 → 89.476 ms**, with no trace
drops/write failures. This measures control/checkpoint overhead, not model or graph-query latency.
The 24-case retrieval suite measured p50 **5.445 → 3.780 ms**; p95 **277.14 → 280.67 ms** did not
improve. Recall@5/MRR remained 1.0 on 18 positives with zero false auto-resolutions. These small
samples are not general accuracy or production performance guarantees. Raw before/after reports
are saved under `data/evaluation/`.

Tests cover 32 deterministic modality/retry/gap scenarios, agent boundary attacks, graph scope,
quality rejection, timeout/cancellation, same-session exclusion, catalog refresh under concurrency,
input/output mutation isolation, actual checkpoint connection restart and live medicinal queries.
Traces include invocation latency/attempt/capability; persistence remains a non-blocking side
channel. Check dropped/write-failure counters before claiming complete academic traces.

Production authentication, distributed session locking, automatic retention, parallel dispatch,
image inference/blob storage and frontend streaming remain separate scoped milestones. The
single-process bounded harness is ready for typed teammate integrations; these exclusions must
not be presented as completed production infrastructure.

## Recorded final checks

The full local integration suite passed 195 tests in 80.22 seconds. After adding the final
trace-shutdown accounting regression, 65 focused trace/integration/orchestration tests passed.
Ruff and strict mypy passed (101 backend source files), pip check passed, and a live HTTP smoke
query completed through the Windows launcher with healthy PostgreSQL/Qdrant endpoints.

Checkpoint implementation follows the [official PostgreSQL checkpointer documentation](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-postgres).

Single-plant scope update: the session plant is locked after discovery. New names can be interpreted
only to detect a different-plant request, never to replace the active plant. Graph requests and
returned scoped evidence are checked at the execution boundary. Terminal empty graph gaps stop
repeating the same query; transient failures retain bounded retry behavior. Non-identity graph
property contradictions do not initiate entity reassessment. See GRAPH_AGENT_GUIDE.md.
