# Backend delivery report

Completed for the single-user academic MVP. The implementation resumes the saved response/API work;
existing Text/Entity and Graph agents remain the specialized capability implementations.

## Delivered behavior

- Versioned `/api/v1` transport delegates to the existing LangGraph harness. Every new chat starts
  in discovery and locks exactly one active plant before conversation follow-ups.
- Durable PostgreSQL messages, session titles/archive state, uploads, operations and replayable SSE.
  Client request UUIDs enforce idempotency. Cancellation, crash interruption and explicit recovery
  preserve the bounded harness lineage, including clarification replies.
- Final response generation is model-agnostic through `TokenModel`, with a local Ollama adapter.
  Qwen3 1.7B formats approved evidence blocks; it cannot query tools/databases or strengthen evidence.
  SSE emits validated chunks after the harness approves response_context. This intentionally does
  not forward unrestricted raw model tokens or generate arbitrary medical paraphrases.
- Evidence snapshots are saved per completed frontend operation. Sources, classes, unknowns and
  educational wording remain deterministic. Formatting failure uses verified-record fallback.
- Shared workspace Bearer authentication, explicit development bypass, bounded capacity and image
  validation. A PostgreSQL advisory lease enforces the documented single-backend-process scope.
- Frontend OpenAPI/SSE schemas, tested fetch/SSE helper, discovery/conversation integration guide,
  Windows PowerShell runbook, model warm-up and reproducible benchmark command.

## Important fixes and validation coverage

Completion event and result commit atomically; SSE also rechecks after observing terminal status,
covering completion racing a batch read. Immediate cancellation works even before a task starts.
Idempotency replays work at full capacity. Restart checks distinguish a pending reply from a saved
question or completed reply, avoiding duplicate application. Historical evidence is not reread from
mutable later clarification state. Checkpoint cleanup precedes chat deletion so failures are retriable.

Tests cover evidence preservation, malformed/incomplete/tool-invoking model frames, safe fallback,
stream cancellation, text limits, policy responses, auth/CORS, history, archive/restore/delete,
image validation/persistence/session scoping, clarification recovery, one-plant enforcement,
SSE replay/order/completion races and frontend Unicode/partial-frame parsing.

## Performance and limitations

The initial cold model load exceeded the35-second budget and fell back. After explicit warm-up,
2/4/8-record synthetic formatting requests measured0.441/0.346/0.594seconds without fallback.
These saved component measurements are not end-to-end latency or medical-accuracy claims.
`ollama ps` confirmed100%GPU placement at4096context on the supplied4GBGPU. Keep-alive is30minutes
in local configuration; use the warm-up command before demonstrations.

The Image Agent now has a supplied 40-class Xception classifier and dedicated Qdrant reference
index behind `IMAGE_ENABLED`; durable upload and integration contracts are
available. The frontend application itself is not built by this backend task. There are no user
accounts, distributed workers or automatic retention jobs. Database-cloud compatibility remains
configuration/interface based; no hosted PostgreSQL, Qdrant or Aura smoke test was performed here.

See [FRONTEND_BACKEND_GUIDE.md](FRONTEND_BACKEND_GUIDE.md) for frontend flows and
[BACKEND_RUNBOOK.md](BACKEND_RUNBOOK.md) for exact setup, migration and run commands.

## Recorded validation runs

These are separate overlapping runs, not additive test counts. The broad integration suite was
completed before the final recovery/SSE fixes; subsequent offline, chat integration and HTTP checks
validate the final affected paths.

| Report | Tests | Passed | Skipped | Failures/errors |
|---|---:|---:|---:|---:|
| [backend_api_tests.xml](data/evaluation/backend_api_tests.xml) | 309 | 307 | 2 | 0 |
| [backend_unit_tests.xml](data/evaluation/backend_unit_tests.xml) | 310 | 275 | 35 | 0 |
| [backend_chat_integration_tests.xml](data/evaluation/backend_chat_integration_tests.xml) | 8 | 8 | 0 | 0 |

Frontend helper:5 Node tests passed. Ruff lint/format checks passed (149 Python files formatted),
mypy passed for112 backend source files, and pip dependency checks passed.

Final real HTTP smoke check on2026-10-15: all four dependency health routes returned200; a real
Neo4j-backed neem question streamed68events and8citations using qwen3:1.7b with no fallback.
First text arrived in2.289seconds, final completion in2.515seconds. Explicit cancellation returned
cancelled. The temporary test chat was deleted. See
[backend_http_smoke.json](data/evaluation/backend_http_smoke.json). These single-run timings are
observations, not percentile guarantees. The backend was left running on localhost:8000.

## Changed and added files

The inventory below covers this response/API delivery. Existing agent query implementations were
not rewritten. The ignored local `.env` was also updated with response-model configuration only;
credentials are not included in this report or checked into Git.

- [.env.example](.env.example)
- [API.md](API.md)
- [DATABASE.md](DATABASE.md)
- [DECISIONS.md](DECISIONS.md)
- [README.md](README.md)
- [SECURITY.md](SECURITY.md)
- [backend/api/dependencies/services.py](backend/api/dependencies/services.py)
- [backend/config/settings.py](backend/config/settings.py)
- [backend/contracts/response.py](backend/contracts/response.py)
- [backend/main.py](backend/main.py)
- [backend/orchestrator/orchestrator.py](backend/orchestrator/orchestrator.py)
- [backend/state/models.py](backend/state/models.py)
- [BACKEND_IMPLEMENTATION_REPORT.md](BACKEND_IMPLEMENTATION_REPORT.md)
- [BACKEND_RUNBOOK.md](BACKEND_RUNBOOK.md)
- [FRONTEND_BACKEND_GUIDE.md](FRONTEND_BACKEND_GUIDE.md)
- [backend/api/export_contracts.py](backend/api/export_contracts.py)
- [backend/api/routes/platform.py](backend/api/routes/platform.py)
- [backend/api/schemas/platform.py](backend/api/schemas/platform.py)
- [backend/database/postgres/chat.py](backend/database/postgres/chat.py)
- [backend/database/postgres/migrations/003_chat_api.sql](backend/database/postgres/migrations/003_chat_api.sql)
- [backend/llm/admin.py](backend/llm/admin.py)
- [backend/llm/guarded.py](backend/llm/guarded.py)
- [backend/llm/ollama.py](backend/llm/ollama.py)
- [backend/services/chat_images.py](backend/services/chat_images.py)
- [backend/services/live.py](backend/services/live.py)
- [backend/services/runs.py](backend/services/runs.py)
- [data/evaluation/backend_api_tests.xml](data/evaluation/backend_api_tests.xml)
- [data/evaluation/backend_chat_integration_tests.xml](data/evaluation/backend_chat_integration_tests.xml)
- [data/evaluation/backend_http_smoke.json](data/evaluation/backend_http_smoke.json)
- [data/evaluation/backend_unit_tests.xml](data/evaluation/backend_unit_tests.xml)
- [data/evaluation/response_model_benchmark.json](data/evaluation/response_model_benchmark.json)
- [data/evaluation/response_model_warm_benchmark.json](data/evaluation/response_model_warm_benchmark.json)
- [frontend/api/client.mjs](frontend/api/client.mjs)
- [frontend/api/client.test.mjs](frontend/api/client.test.mjs)
- [frontend/contracts/openapi.json](frontend/contracts/openapi.json)
- [frontend/contracts/stream-event.schema.json](frontend/contracts/stream-event.schema.json)
- [tests/api/test_platform_auth.py](tests/api/test_platform_auth.py)
- [tests/api/test_platform_live.py](tests/api/test_platform_live.py)
- [tests/unit/test_response_streaming.py](tests/unit/test_response_streaming.py)
- [tests/unit/test_sse_completion.py](tests/unit/test_sse_completion.py)
> **Historical/design reference (updated 2026-10-18).** The active implementation is the DeepAgents main orchestrator with three specialist subagents, plus an outer LangGraph checkpoint/clarification adapter. This document may describe the removed deterministic harness, prior response policies, old test counts, or planned features. For current behavior use [implemented architecture](docs/architecture/README.md), [API and frontend](docs/api-and-frontend/README.md), [file map](docs/repository-map/README.md), and the source code. Do not treat historical statements below as current runtime guarantees.
