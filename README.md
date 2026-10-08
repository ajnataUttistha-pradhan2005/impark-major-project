# IMPARK

Indian Medicinal Plant Agentic Retrieval and Knowledge System — phase-one academic foundation.

This is a runnable control-plane scaffold, not a plant identification or medical advice product.
Exactly three specialized agents exist. The Python harness owns deterministic decisions and
LangGraph provides the cycle and interrupt/checkpoint runtime.

## Run locally

Python 3.12+ is required. From the repository root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open `/health` and `/docs` on localhost:8000. `.env.example` explicitly enables the local-only
development API. Without that setting, `/dev/*` is denied. Production environment always denies
the development bypass. Authentication/ownership enforcement is not implemented yet.

Development sessions, images' metadata, traces, and LangGraph checkpoints are **in memory**.
Use one worker. Restarting loses them. Health is liveness, not datastore readiness.
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

- **IMPLEMENTED:** typed contracts/state, action registry, eligibility and weighted decisions,
  bounded LangGraph cycle, interrupt/resume, invocation timeouts/retries, basic evidence reducers,
  deterministic context builder, local HTTP session/history/upload endpoints, safe errors,
  correlation middleware, structured application logs, non-blocking trace buffer/background writer,
  OpenTelemetry API span hooks, architecture tests.
- **SCAFFOLDED:** durable storage ports, image inference/vector ports, entity search/disambiguation/
  coreference ports, transport-neutral streaming events, offline evaluation records/snapshots,
  authorization hook. Graph objective interpretation and rich follow-ups are not wired to chat yet.
  The harness supports graph objectives supplied by typed domain state in tests.
- **PLACEHOLDER:** three default agents, Final LLM, autocomplete, in-memory storage/checkpoints/sink.
  No actual Neo4j/Qdrant/model call, database migration, frontend UI, live streaming transport,
  telemetry exporter or evaluation dashboard exists.
- **TODO / DECISION REQUIRED:** see `DECISIONS.md` R-001–R-018 and `FOUNDATION_REPORT.md`.
  Dynamic parallel execution is deferred; this foundation chooses one eligible action at a time.

Trace loss never changes decisions. The provisional buffer drops newest events when full and counts
write failures; shutdown flush is bounded. A benchmark must reject an incomplete trace rather than
claim full reconstruction. Trace persistence awaits only in the background writer. Snapshots retain
IDs, confidence and control status, not raw user text or documents.

## Compose

`docker compose up --build backend` runs the standalone memory foundation. Optional stores use
`docker compose --profile stores up -d postgres redis neo4j qdrant`, after configuring local
credentials. They are not connected to the backend yet. Ports bind to loopback. Neo4j retrieval will
need a separate read-only principal. Frontend/model/telemetry services will be added when selected.

The supplied architecture documents remain the source of truth. This phase does not mark later
roadmap milestones complete.
