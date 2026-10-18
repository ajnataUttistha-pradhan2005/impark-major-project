# Testing, evaluation, and verified limits

This page maps the current test suites to the behavior they exercise. A passing fixture test proves its stated contract, not scientific validity for arbitrary plants/questions or performance on another machine. Run from the repository root after installing the `dev` extra:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m mypy backend
Push-Location frontend
npm test
npm run typecheck
npm run build
Pop-Location
```

## Suite map

| Directory | What it checks |
| --- | --- |
| `tests/deepagents/` | Current DeepAgents tool delegation/boundaries, LangGraph adapter, follow-up context and response quality. |
| `tests/api/` | Chat API, authentication, contract/stream behavior, and opt-in live backend/proxy/image/Ollama cases. |
| `tests/text/` | Name search, provider configuration, candidate resolution, intent helpers and opt-in live stores. |
| `tests/graph/`, `tests/neo4j/` | Typed graph retrieval, driver/repository, scoped reads and opt-in live database cases. |
| `tests/unit/` | Evidence/response helpers, contracts, SSE completion and image behavior. Some tests cover retained utilities outside the ordinary DeepAgents path. |
| `tests/integration/`, `tests/evaluation/`, `tests/llm/` | Cross-layer boundaries, trace behavior and opt-in real-model explanations. |
| `frontend/api/client.test.mjs`, `frontend/src/sessionPages.test.mjs` | HTTP/SSE client and paginated/stale sidebar refresh behavior. |

Live test toggles include `CHAT_RUN_INTEGRATION`, `GRAPH_RUN_INTEGRATION`, `SEARCH_RUN_INTEGRATION`, `NEO4J_RUN_INTEGRATION`, `IMAGE_RUN_INTEGRATION`, and `OLLAMA_RUN_INTEGRATION`. Inspect the relevant test's preconditions before enabling it. In particular, the backend owns a single-process PostgreSQL lease, so live tests that create the app may require stopping the demo server. Neo4j write tests have a separate opt-in; do not run write tests against the research/production graph. `backend/evaluation/text_discovery.py` evaluates name discovery; `trace_audit.py` audits domain traces. Historical deterministic-harness benchmarks are not a current DeepAgents evaluation claim.

## Traces and interpretation

`backend/trace/recorder.py` buffers typed domain events and writes them through its sink off the control path. `backend/trace/instrumentation.py` adds correlation/technical spans. The public run event stream in PostgreSQL is a **different** mechanism used for UI replay. DeepAgents emits selected lifecycle/observation/clarification/response trace events; model internals and all subagent reasoning are not fully exposed by the domain trace. A trace outage must not be interpreted as a model failure, but it reduces audit completeness. The event and state models are under `backend/trace/` and `backend/state/`.

## Material limitations and unverifiable claims

- The main model may add useful pretrained scientific context, but the project has no independent fact checker for every such sentence. Response checks catch certain unsupported claims, unknown citations, unfinished plans and formatting issues; they cannot certify every explanation.
- A cited graph relation is not a clinical finding. Evidence classes and provenance must remain distinct from general botanical/pharmacological explanation, especially for efficacy, safety, dosage and mechanisms.
- Image classification is scoped to the supplied 40 leaf classes and the quality of its training/reference data; a candidate requires confirmation. There is no validated broad non-plant or plant-part classifier in the current API capabilities.
- Qdrant semantic name search is optional and can be unavailable while PostgreSQL search remains available. Index freshness depends on explicit `sync`; web startup does not self-heal a stale projection.
- The current demo is single-workspace and single backend process. Its PostgreSQL lease, in-process run task map, per-session locks and local model hardware have not been validated as a horizontal-scale architecture.
- `GET /health/llm` tests configuration presence only. Live model response, source correctness, latency, token use, and multilingual breadth need separate evaluation against actual data.
- Dated reports may record measurements from a prior checkout/hardware/data snapshot. Do not treat them as current benchmark results. To reproduce a claim, record the Git revision, service versions, dataset/search generation, model/provider, test flags, hardware, command and output.

This documentation task changed Markdown only and did not execute live database/model experiments; the latest scientific or latency quality remains whatever your own current run demonstrates.
