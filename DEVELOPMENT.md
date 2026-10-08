# DEVELOPMENT.md — Development Setup and Workflow

## 1. Current repository status

Phase-one foundation added 2026-10-08. Exact local commands:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m mypy backend
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

See README.md for opt-in local API configuration. This foundation uses memory adapters and needs no
running datastore. The full-stack bootstrap below describes later integration, not phase-one
requirements. Windows sandbox environments may need permission for asyncio loopback sockets.

The supplied project material specifies the target architecture but does not include an existing source-code repository scaffold.

Therefore Codex must inspect the actual repository and its manifests before running package-manager/build commands. Do not claim commands are available until their files exist.

## 2. Prerequisites

Target baseline:

- Python 3.12+
- Docker / Docker Compose
- Git
- Node.js runtime for the selected React/Next.js frontend
- local compute sufficient for Neo4j, Qdrant and optional Ollama/model inference

Exact versions beyond Python are `TODO / DECISION REQUIRED` until committed.

## 3. Bootstrap sequence

```text
1. inspect repository
2. read AGENTS.md
3. inspect package/manifests/config
4. create .env from .env.example
5. start PostgreSQL / Redis / Neo4j / Qdrant using Compose
6. install backend dependencies using committed packaging
7. install frontend dependencies using committed package manager
8. run migrations
9. seed data where available
10. start backend
11. start frontend
12. run tests
13. verify trace/evaluation output
```

## 4. Environment variables

Expected configuration categories include:

```text
APPLICATION_ENV
DATABASE_URL
REDIS_URL
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
QDRANT_URL
LLM_PROVIDER
LLM_MODEL
OLLAMA_BASE_URL
VLLM_BASE_URL
CORS_ORIGINS
TRACE_BUFFER_SIZE
MAX_ITERATIONS
MAX_AGENT_RETRIES
REPEATED_ACTION_THRESHOLD
ENTITY_CONFIDENCE_THRESHOLDS
```

The final Pydantic configuration model is authoritative once implemented. Not every deployment requires every variable.

## 5. Compose topology

Intended local services:

```text
FastAPI application
frontend
PostgreSQL
Redis
Neo4j
Qdrant
Ollama/model service as configured
OpenTelemetry collector if used
Prometheus
Grafana
```

Do not add Kubernetes or distributed brokers for the core demonstration.

## 6. Backend runtime

```text
FastAPI
  ↓
LangGraph runtime
  ↓
Python harness
  ↓
three specialized agents/providers
  ↓
evidence/belief/state
  ↓
termination/replan
  ↓
Final LLM
  ↓
stream response
```

The trace subsystem observes these steps asynchronously.

## 7. Database development

Start PostgreSQL, Neo4j and Qdrant before integration tests that require them.

Migration commands depend on the selected migration tool. Once selected, record the exact commands here and in `README.md`.

Do not depend on startup-time schema mutation.

## 8. Model development

Ollama is the preferred local development path. vLLM is optional for throughput testing.

The exact model must be selected through quality/performance benchmarking and recorded in `DECISIONS.md`.

Provider abstraction:

```text
LLMProvider
├── OllamaProvider
├── VLLMProvider
└── compatible adapter if later justified
```

## 9. Frontend development

### Discovery

The UI should support:

- plant name search,
- autocomplete,
- natural-language plant description,
- image upload/drag-and-drop,
- text + image,
- candidate selection.

### Conversation

Support:

- active plant context,
- stateful follow-up,
- new image attachment,
- streaming progress/answer,
- evidence/citation presentation,
- clarification.

Do not display hidden model reasoning.

## 10. Trace viewer

The trace viewer is an evaluation/research surface, not part of task control.

It should allow a reviewer to inspect:

```text
run
→ turn
→ iteration
→ eligible actions
→ decision
→ action/invocation
→ observation/failure
→ evidence
→ belief/state update
→ retry/clarification
→ termination
```

Do not expose secrets/private prompts/hidden reasoning.

## 11. Testing workflow

Run focused tests while implementing and the broader test suite before milestones.

Expected groups:

```text
unit
integration
orchestration
agentic
api
evaluation
all
```

Exact commands must be written once the repository chooses its tools.

## 12. Validation workflow

```text
read task
→ inspect implementation/tests
→ identify affected modules
→ implement smallest change
→ add/update tests
→ add trace coverage
→ run focused checks
→ run broader checks
→ review diff
→ update docs/decisions
```

## 13. Debugging workflow

For a wrong action, inspect the persisted sequence:

```text
state snapshot
→ eligible actions
→ decision score/reason
→ selected action
→ observation/failure
→ evidence evaluation
→ belief update
→ termination
```

Use the trace store, not only logs.

## 14. Trace debugging requirement

A new control path is incomplete until its behavior can be reconstructed through domain events/snapshots.

At minimum capture:

```text
decision
action
invocation
observation/failure
belief/evidence update
termination/replan
```

## 15. Performance checks

Measure:

- agent invocation frequency,
- average/P95 latency,
- LLM calls,
- graph queries,
- token usage,
- repeated/unused actions,
- parallel benefit.

Do not optimize away trace/evidence required for evaluation.

## 16. Data/benchmark workflow

```text
source data
→ process/normalize
→ seed stores
→ benchmark cases
→ run system
→ persist trace/results
→ compute metrics
```

Benchmark labels must not be changed to hide implementation failures.

## 17. Reproducibility

Correlate benchmark runs with:

```text
run_id
session_id
turn_id
```

Record provider/model versions where available. Control or record nondeterminism for benchmark analysis when practical.

## 18. Dependency changes

Before adding a dependency:

- inspect existing packages,
- confirm it is needed,
- verify Python/frontend compatibility,
- add through the committed package manager,
- update tests/docs/config,
- add a decision record when architecture is materially affected.

## 19. Security validation

Before a milestone is complete, verify:

- no secret in source/log/trace,
- no raw Cypher path,
- graph credentials are least-privilege/read-only,
- invalid images are rejected,
- final LLM remains isolated,
- trace failure does not fail the task.
