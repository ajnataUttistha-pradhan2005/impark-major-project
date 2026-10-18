# Repository and file map

This is a navigation map for the files present in the inspected checkout. Names can outlive their original role: a module is called *active* here only when reached from `backend/main.py`, its API routes, or the current DeepAgents path. Tests and offline commands may import additional modules. `__init__.py` files establish Python packages; `next-env.d.ts` is Next.js-generated typing. Data/model artifacts are described in [setup and operations](../setup-and-operations/README.md).

## Root, tooling, and training

| Path | Responsibility |
| --- | --- |
| `README.md`, `docs/*.md` | Entry point and current implemented system documentation. |
| `AGENTS.md`, `INSTRUCTIONS.md`, `CODING_STANDARDS.md`, `SECURITY.md`, `TESTING.md`, `DECISIONS.md`, `TASKS.md`, `CODEX_WORKFLOW.md` | Repository instructions, policies, tests, decisions, and roadmap; current implementation takes precedence over historical planning text. |
| `ARCHITECTURE.md`, `PROJECT_STRUCTURE.md`, `API.md`, `DATABASE.md`, `DEVELOPMENT.md` | Top-level topic entry points; current details are maintained under `docs/`. |
| `*_REPORT.md`, `*_GUIDE.md`, `FOUNDATION_REPORT.md` | Feature reports and guides; dated reports are historical snapshots where marked. |
| `design.md` | Frontend visual/UX specification, not a backend runtime contract. |
| `pyproject.toml`, `requirements-dev.lock` | Python package/dependency metadata and captured development versions. |
| `Dockerfile`, `docker-compose.yml` | Backend image and local optional `stores` profile (PostgreSQL, Qdrant, Neo4j, Redis). |
| `.env.example`, `.gitignore` | Safe configuration template and ignored secrets/generated artifacts. |
| `scripts/demo.ps1` | Local demo launcher/readiness and warmup. |
| `scripts/demo_warmup.py`, `scripts/smoke_backend.py` | Readiness/model warmup and smoke checks. |
| `scripts/configure_local_search.py` | Local search-configuration helper. |
| `scripts/export_team_handoff.ps1` | Explicit cold export of selected database volumes/images and image assets for teammate transfer. |
| `training/image/train_model.py` | Preserved image-model training recipe; not executed by the API. |

## Application composition, transport, and services

| Path | Responsibility |
| --- | --- |
| `backend/__main__.py`, `backend/runtime.py` | Module entry point and event-loop setup. |
| `backend/main.py` | FastAPI factory, dependency lifecycle, health routes, and router wiring. |
| `backend/config/settings.py` | Pydantic environment settings and cross-setting validation. |
| `backend/api/routes/platform.py` | Versioned `/api/v1` sessions, runs, SSE, evidence, autocomplete, and images. |
| `backend/api/routes/conversations.py`, `images.py` | Development-only `/dev` synchronous routes. |
| `backend/api/schemas/chat.py`, `platform.py` | Public Pydantic chat/session/run/message/SSE contracts. |
| `backend/api/dependencies/services.py`, `neo4j.py` | Route dependency/authorization helpers. |
| `backend/api/middleware.py` | Correlation ID and logging middleware. |
| `backend/api/streaming.py` | Streaming helpers; durable `/api/v1` SSE loop is in `platform.py`. |
| `backend/api/export_contracts.py` | Exports OpenAPI and stream-event JSON schemas into `frontend/contracts`. |
| `backend/services/conversations.py` | Session creation, state load, turn/clarification invocation, active-plant lock, public-state projection. |
| `backend/services/runs.py` | Durable operation acceptance, idempotency, background execution, event writer, cancel/resume/delete. |
| `backend/services/live.py` | Context-local event publisher used by runtime and operation wrapper. |
| `backend/services/chat_images.py`, `images.py` | Persistent and development image registration/validation. |
| `backend/services/errors.py` | Domain-to-HTTP service errors. |

## Current DeepAgents path and domain contracts

| Path | Responsibility |
| --- | --- |
| `backend/orchestrator/deepagents/runtime.py` | Main agent, three compiled subagents, bound tools, retrieval coverage, answer repair/citations/fallback. |
| `backend/orchestrator/deepagents/models.py` | Cached, per-role LangChain/Ollama chat-model construction. |
| `backend/orchestrator/deepagents/prompts.py` | Main, graph specialist, and repair instructions. |
| `backend/orchestrator/deepagents/context.py` | Bounded recent-dialogue/cited-fact prompt and short-follow-up resolution. |
| `backend/orchestrator/deepagents/response_quality.py` | Post-generation cleaning, citation attachment, and bounded response checks. |
| `backend/orchestrator/deepagents/graph.py` | Outer LangGraph state graph and checkpointed clarification interrupt. |
| `backend/orchestrator/deepagents/clarification.py` | Validates/applies candidate or image clarification. |
| `backend/orchestrator/deepagents/host.py` | Specialist service bindings and trace/progress emission; not a planner. |
| `backend/orchestrator/deepagents/README.md` | Detailed active runtime guide. |
| `backend/state/models.py`, `goals.py` | Persisted conversation, session, context, belief, execution, termination, budget and goal types. Some fields preserve historical schema compatibility. |
| `backend/contracts/base.py` | Shared contract base, IDs, confidence and correlation metadata. |
| `backend/contracts/agents.py` | `QueryType`, scoped graph inputs, candidate/image/text/graph observations and failures. |
| `backend/contracts/actions.py` | Typed action/invocation metadata used by specialists and traces; not the active action-selection engine. |
| `backend/contracts/evidence.py` | Evidence classes, provenance, graph paths, gaps and contradictions. |
| `backend/contracts/response.py` | Clarification, response, response-context and stream-related types. |
| `backend/agents/common/bundle.py`, `services.py`, `contracts.py`, `parts.py` | Test overrides, three specialist bindings, shared interfaces and plant-part vocabulary. |

## Specialists and retrieval

| Path | Responsibility |
| --- | --- |
| `backend/agents/text/agent.py`, `providers.py` | Typed Text Agent wrapper/provider interface. |
| `backend/agents/text/search.py` | Hybrid name/alias candidate search combining catalog, PostgreSQL and optional vectors. |
| `backend/agents/text/resolver.py`, `catalog.py`, `embeddings.py` | Normalization/ranking, catalog representation, FastEmbed provider. |
| `backend/agents/text/interpretation.py` | Typed topic interpretation used by the bounded coverage/fallback path. |
| `backend/agents/text/semantic_intent.py`, `intent_model.py`, `open_question.py` | Additional natural-language interpretation utilities; inspect call sites before treating one as the main DeepAgents planner. |
| `backend/agents/graph/agent.py`, `retrieval.py` | Graph observation wrapper and allow-listed read-only plant retrieval/evidence construction. |
| `backend/agents/image/agent.py`, `providers.py` | Image observation wrapper/provider interface. |
| `backend/agents/image/model.py`, `inference.py`, `preprocessing.py`, `quality.py` | Xception loading/inference, input processing, and quality assessment. |
| `backend/agents/image/retrieval.py`, `ranking.py` | Image-vector nearest-neighbor search and CNN/vector fusion. |
| `backend/agents/image/admin.py`, `build_index.py`, `evaluate.py` | Explicit offline extraction, Qdrant index build and image evaluation. |
| `backend/agents/{text,graph,image}/README.md` | Specialist-specific instructions and limits. |

## Data, evidence, output, and observability

| Path | Responsibility |
| --- | --- |
| `backend/database/neo4j/config.py`, `driver.py`, `client.py`, `errors.py` | Validated connection config, shared driver lifecycle, query/transaction operations, errors. |
| `backend/database/neo4j/queries.py`, `medicinal.py`, `repository.py`, `models.py` | Code-owned medicinal graph query templates/repositories/records. |
| `backend/database/neo4j/diagnostics.py`, `__main__.py` | Read-only graph diagnostics CLI. |
| `backend/database/postgres/client.py` | Async PostgreSQL pool and parameterized operations. |
| `backend/database/postgres/chat.py`, `persistence.py`, `repositories.py` | Durable API operation/chat store, session/trace persistence, repository interfaces. |
| `backend/database/postgres/checkpoints.py` | PostgreSQL LangGraph checkpoint context. |
| `backend/database/postgres/search.py` | PostgreSQL plant-name/alias search. |
| `backend/database/postgres/migrate.py`, `migrations/001_search.sql` … `004_reference_notes.sql` | Explicit versioned schema and checkpoint setup; no automatic startup migration. |
| `backend/database/qdrant/client.py`, `repository.py` | Vector connection/collection operations and text-vector repository. |
| `backend/database/search_config.py`, `search_admin.py`, `search_sync.py` | Store settings, explicit migrate/sync/health CLI, Neo4j-to-search projection. |
| `backend/database/memory.py`, `redis/repository.py` | Development memory repository and optional Redis adapter; Redis is not wired in `create_app()`. |
| `backend/evidence/reference.py`, `reference_import.py` | Verified reference-note lookup and explicit importer. |
| `backend/evidence/context_builder.py`, `plant_context.py`, `evaluator.py` | Earlier response-context/evidence utilities retained in the tree; the active main answer path is `deepagents/runtime.py`. |
| `backend/llm/grounded.py` | Active grounded fallback used when DeepAgents generation/revision fails. |
| `backend/llm/{provider,ollama,guarded,plant_context,knowledge_explanation,narrative,concise,verbalize,part_glossary,admin}.py` | Older/configurable generation and wording utilities or explicit model administration. They are not the ordinary DeepAgents answer pipeline; check imports before removal. |
| `backend/trace/recorder.py`, `models.py`, `instrumentation.py` | Buffered domain trace, event types and technical instrumentation. |
| `backend/evaluation/models.py`, `text_discovery.py`, `trace_audit.py` | Evaluation contracts, name-discovery evaluation and trace audit; see `backend/evaluation/README.md`. |

## Next.js frontend and tests

| Path | Responsibility |
| --- | --- |
| `frontend/app/layout.tsx`, `page.tsx`, `chat/[id]/page.tsx` | Root layout, landing, and chat route. |
| `frontend/app/api/v1/[...path]/route.ts` | Server-side same-origin backend proxy. |
| `frontend/src/App.tsx`, `api.ts`, `types.ts`, `styles.css` | Application state/flow, typed API facade, TypeScript contracts, responsive styling. |
| `frontend/src/components/{Discovery,Clarification,Conversation,Evidence,Sidebar,Upload,Icons}.tsx` | Discovery, resume, transcript/composer, citation panel, session list, image input and icons. |
| `frontend/api/client.mjs`, `client.d.mts`, `client.test.mjs` | HTTP/SSE transport, types and transport tests. |
| `frontend/src/sessionPages.mjs`, `sessionPages.test.mjs` | Paginated session collection and stale-refresh tests. |
| `frontend/contracts/openapi.json`, `stream-event.schema.json` | Exported backend contract snapshots. |
| `frontend/package.json`, `package-lock.json`, `next.config.ts`, `tsconfig.json`, `.env.example`, `README.md` | Dependency scripts, Next/TS config, environment template and UI guide. |
| `tests/api/` | API contract/auth, streaming and opt-in live frontend/backend checks. |
| `tests/deepagents/` | Current runtime, context/response quality and graph-adapter regression tests. |
| `tests/text/`, `tests/graph/`, `tests/neo4j/` | Specialist/search and repository unit/live tests. |
| `tests/unit/`, `tests/integration/`, `tests/evaluation/`, `tests/llm/` | Contract, response, boundary, trace and opt-in model tests. |
| `tests/conftest.py` | Shared fixtures and test configuration. |
