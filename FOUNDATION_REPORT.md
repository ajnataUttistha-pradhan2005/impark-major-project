# Phase-one implementation report — 2026-10-08

## Scope and status

Created the foundation requested in the attached prompt after reading all 13 supplied documents.
The application remains an academic scaffold; no real botanical identification or medicinal
knowledge retrieval is claimed.

**IMPLEMENTED**

- Python-package-ready backend with API -> service -> harness -> capability/provider boundaries.
- FastAPI factory, health, dependency wiring, configuration, safe errors, correlation middleware,
  structured application logging and opt-in development routes.
- Shared Pydantic v2 contracts for session/chat, correlation, actions/candidates/decisions,
  invocations/retries, observations/failures, evidence/provenance, graph/image/text inputs and outputs,
  clarification, response context, final response and transport-neutral server events.
- Typed state separating goals/objectives, beliefs, evidence, execution, control and active context.
- Twelve-action registry, deterministic eligibility/scoring, iteration/action/repetition/retry/
  clarification bounds, timeout handling, terminal-state protection.
- Actual LangGraph cycle with conditional decisions, state reducers, memory checkpoints and real
  clarification interrupts/resume preserving session/run/turn lineage.
- Safe image decoding off-loop, MIME/content/byte/dimension/pixel checks; registered references are
  scoped to a session. No arbitrary URL/path retrieval.
- Typed graph allow-list/parameter/limit/timeout/read-only contracts with no raw Cypher surface.
- Deterministic evidence/context scaffolding, explicit limitations and citation-ID validation.
- Non-blocking trace enqueue/background writer, bounded queue, loss/failure counters, bounded
  shutdown, sanitized snapshots and OpenTelemetry API span hooks.

**SCAFFOLDED**

- PostgreSQL session/domain/trace/evaluation repository ports; Redis cache, Neo4j graph and Qdrant
  vector ports. No physical schema, migration or database driver was added.
- Entity search/extraction/coreference/disambiguation and image inference provider interfaces.
- Streaming event/subscription protocol; no SSE/WebSocket transport chosen.
- Evaluation record contracts and ordered snapshot reconstruction inputs.
- Frontend, data and optional Langflow ownership documentation; no empty framework tree.
- Docker backend plus optional local datastore profile; CI configuration for Python 3.12/3.13.

**PLACEHOLDER**

- Default Text, Image and Graph agents; they return no fabricated candidates/evidence.
- Final LLM and autocomplete; intentional unconfigured responses.
- Session repository, trace sink and LangGraph checkpoint storage are process-local memory.

## Created and modified files

Created: `backend/` (contracts, state, API, services, config, orchestrator, three agents, evidence,
database ports, LLM, trace, evaluation); all six test groups; `scripts/smoke_backend.py`;
`frontend/README.md`, `data/README.md`, `langflow/README.md`; root README, packaging/dependency lock,
Dockerfile/Compose, environment example, Git ignore/attributes, GitHub Actions and this report.

Modified supplied documents only to record implementation status/decisions:
`API.md`, `DEVELOPMENT.md`, `SECURITY.md`, `DECISIONS.md`. Other supplied documents were preserved.
Git was initialized on `main`; all files are initial additions because no prior Git history existed.
Intent-to-add entries permit diff review without staging contents. No commit, remote or push.

## Tests and validation executed

Commands below use `.venv/Scripts/python.exe` on Windows:

| Command/check | Result |
|---|---|
| `python -m pytest -q` | 51 passed |
| `python -m ruff check backend tests scripts` | Passed |
| `python -m ruff format --check backend tests scripts` | Passed |
| `python -m mypy backend` | Passed, 70 source files, strict mode |
| `python -m compileall -q backend` | Passed |
| `python scripts/smoke_backend.py` | 69 modules imported, 52 schemas validated; real Uvicorn HTTP health passed; process stopped |
| `python -m pip check` | No broken requirements |
| `docker compose config --quiet` | Passed syntax/config validation |
| `git diff --check` | Reviewed and whitespace corrected |
| Targeted credential-pattern scan | No matches in source/tests/environment example/Compose/lock |

Tests cover schema boundaries, state isolation, action registry/eligibility, meaningful state-driven
action changes, conflict/gap feedback, terminal states, loop guards, bounded retries, graph/image
placeholder contracts, real clarification resume, existing-context agent skipping, graph-gap
retrieval followed by early completion, evidence-class preservation, forged citation rejection,
trace slow/full/broken sinks, trace reconstruction/privacy, API validation/correlation/auth hook,
and image content checks. Synthetic fixtures are never installed as real plant intelligence.

Windows sandbox initially blocked venv/pip setup and asyncio's internal socketpair; approved
outside-sandbox runs completed setup and runtime validation. Initial interrupted test processes
were stopped. CI and live datastore containers were not run; Compose validation is not a claim of
database connectivity. Python 3.12 CI is configured but this machine's tests used Python 3.13.

## Assumptions, conflicts and open decisions

- Local memory, one worker and provisional `/dev` routes keep the foundation runnable while
  R-002/R-004/R-005 remain unresolved. No production authentication or horizontal deployment claim.
- Explicit prompt takes precedence over illustrative vision pipelines: future pretrained/custom CNN
  classification, with a vector-retrieval port; no model selection was silently made.
- Domain trace enum values use lower-case event names from the prompt; the database document's
  upper-case list is treated as conceptual naming. No physical event schema is frozen.
- Provisional upload limits and metadata-only lifecycle are R-016. Real inference needs retained
  pixels behind a blob repository. Trace overflow/retention settings remain provisional R-012/R-013.
- Goal interpretation and rich follow-ups remain R-017. The chat scaffold creates discovery goals;
  typed domain tests supply graph objectives. Arbitrary chat does not yet retrieve medicinal facts.
- R-018 records semantic validation required before a real Final LLM is enabled. The placeholder
  cannot inflate clinical claims; citation validation alone is not prose-grounding enforcement.
- Parallel execution, real provider adapters, durable checkpoints/traces, streaming transport,
  full multimodal resolution, ingestion and benchmark dashboards belong to later phases.
- Existing R-001–R-015 decisions remain open. See DECISIONS.md for exact scope and temporary choices.

No architectural inconsistency was silently resolved as a permanent design choice. The supplied
documents' full-system roadmap was bounded by the explicit first-phase scope.
> **Historical/design reference (updated 2026-10-18).** The active implementation is the DeepAgents main orchestrator with three specialist subagents, plus an outer LangGraph checkpoint/clarification adapter. This document may describe the removed deterministic harness, prior response policies, old test counts, or planned features. For current behavior use [implemented architecture](docs/architecture/README.md), [API and frontend](docs/api-and-frontend/README.md), [file map](docs/repository-map/README.md), and the source code. Do not treat historical statements below as current runtime guarantees.
