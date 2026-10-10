# IMPARK

Indian Medicinal Plant Agentic Retrieval and Knowledge System: an academic demonstration with
text/entity discovery, typed medicinal-plant graph retrieval and a bounded stateful harness.
Exactly three specialized agents exist. The harness owns deterministic decisions and LangGraph
provides checkpointed control flow. Image inference remains a teammate milestone.

See [TEXT_ENTITY_GUIDE.md](TEXT_ENTITY_GUIDE.md) for store setup and [HARNESS_GUIDE.md](HARNESS_GUIDE.md)
for optimization results, durable recovery and teammate integration. Shared Neo4j details remain
in [NEO4J_GUIDE.md](NEO4J_GUIDE.md).

## Run locally

Python 3.12+ is required. From the repository root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m backend
```

Open `/health` and `/docs` on localhost:8000. `.env.example` explicitly enables the local-only
development API. Without that setting, `/dev/*` is denied. Production environment always denies
the development bypass. Authentication/ownership enforcement is not implemented yet.

With text search disabled, the foundation uses in-memory providers. With it enabled, sessions,
traces and LangGraph checkpoints use PostgreSQL after explicit migration/import. Use one worker.
Health is liveness; individual datastore health endpoints report readiness.
Image bytes are validated then discarded; real inference needs the future blob-storage adapter.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m mypy backend
```

The tested development environment is recorded in `requirements-dev.lock` (Python 3.13).
For reproducibility install it before `pip install --no-deps -e .`; dependency ranges in
`pyproject.toml` remain the cross-platform package contract. CI checks Python 3.12 and 3.13.

## Local API example

```powershell
$session = Invoke-RestMethod -Method Post http://127.0.0.1:8000/dev/conversations
$sessionId = $session.correlation.session_id
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/dev/conversations/$sessionId/turns" -ContentType application/json -Body '{"text":"Tulsi"}'
```

The placeholder Text Agent returns no candidates. A turn therefore asks for clarification,
checkpoints, and resumes on the same run/turn lineage when another message arrives. Clarifications,
retries, equivalent actions and iterations are bounded. Eventually the system returns an explicit
evidence-unavailable outcome. It does not pretend to identify Tulsi.

`/dev/conversations/{id}/images` accepts raw PNG/JPEG/WebP bytes with the matching Content-Type.
Submit the returned `image_id` in a turn, optionally with text. Limits are provisional:
5 MiB, 8192 pixels per dimension and 16 million total pixels; settings may lower them.

## Ownership and boundaries

| Area | Files / owner boundary |
|---|---|
| Frontend teammate | `frontend/`; consume API, never select agents |
| Graph teammate | `backend/agents/graph/`; typed `GraphQuery` -> observation/failure |
| Image teammate | `backend/agents/image/`; validated reference -> pretrained/custom CNN adapter |
| Text / Entity | `backend/agents/text/`; normalization and replaceable resolver provider |
| Backend | `backend/api/`, `backend/services/`, `backend/config/` |
| Harness | `backend/orchestrator/`, `backend/state/`, `backend/evidence/` |
| Shared contracts | `backend/contracts/`; request all cross-team contract changes here |
| Response | `backend/llm/`; only deterministic `FinalResponseRequest.response_context` |
| Trace / evaluation | `backend/trace/`, `backend/evaluation/` |
| Persistence | `backend/database/{postgres,redis,neo4j,qdrant}/` |

Agents implement `Agent[InputT].execute(...) -> Observation | Failure`. Inputs contain selected
invocation metadata, never global state. Tests use synthetic fixtures explicitly; no seed knowledge
or trained model is bundled. The graph query object has no Cypher field.

## Implementation status

- Implemented: typed bounded LangGraph harness, deterministic policy, evidence/recovery,
  shared Neo4j interface, PostgreSQL/Qdrant search stores, full documented Text Agent discovery
  paths, typed medicinal-plant retrieval, background traces and offline evaluation.
- Text search runs with `TEXT_SEARCH_ENABLED=true` after explicit migration/import. Without it,
  the development foundation remains available with placeholder providers.
- Image inference, frontend UI, production authorization, live streaming transport and distributed
  session locking remain unfinished. Use one backend worker.
- Decision-model fallback and its experimental artifacts have been removed.

See [Text Entity Guide](TEXT_ENTITY_GUIDE.md) for exact PowerShell setup, environment switching
and discovery API examples, and [Implementation Report](TEXT_ENTITY_IMPLEMENTATION_REPORT.md)
for measurements and limitations. Neo4j setup remains in [NEO4J_GUIDE.md](NEO4J_GUIDE.md).

Trace loss never changes decisions. The provisional buffer drops newest events when full and counts
write failures; shutdown flush is bounded. A benchmark must reject an incomplete trace rather than
claim full reconstruction. Trace persistence awaits only in the background writer. Snapshots retain
IDs, confidence and control status, not raw user text or documents.

## Compose

`docker compose up --build backend` runs the standalone memory foundation.
For the configured text backend, follow the guide and start only PostgreSQL/Qdrant with
`docker compose --profile stores up -d postgres qdrant`; retain the existing `neo4j-dev` container.
Store ports bind to loopback and data lives in named volumes.

See [HARNESS_GUIDE.md](HARNESS_GUIDE.md) for checkpoint recovery, measured optimizations and teammate contracts.

Graph Agent completion and the current one-plant-per-chat policy are documented in
[GRAPH_AGENT_GUIDE.md](GRAPH_AGENT_GUIDE.md). This supersedes earlier inline plant switching and
cross-plant comparison behavior. The Graph Agent is implemented; the image model and frontend UI
remain separate milestones.
