# PROJECT_STRUCTURE.md — Repository Structure

## 1. Target tree

```text
project/
├── backend/
│   ├── api/
│   │   ├── routes/
│   │   ├── schemas/
│   │   └── dependencies/
│   ├── state/
│   │   ├── models.py
│   │   ├── goals.py
│   │   └── checkpoints.py
│   ├── orchestrator/
│   │   ├── graph.py
│   │   ├── orchestrator.py
│   │   ├── actions.py
│   │   ├── policy.py
│   │   ├── decision.py
│   │   ├── execution.py
│   │   ├── recovery.py
│   │   └── termination.py
│   ├── agents/
│   │   ├── common/
│   │   │   ├── contracts.py
│   │   │   └── observations.py
│   │   ├── text/
│   │   │   ├── agent.py
│   │   │   ├── resolver.py
│   │   │   └── providers.py
│   │   ├── image/
│   │   │   ├── agent.py
│   │   │   ├── preprocessing.py
│   │   │   ├── embeddings.py
│   │   │   ├── ranking.py
│   │   │   └── providers.py
│   │   └── graph/
│   │       ├── agent.py
│   │       ├── queries.py
│   │       ├── validator.py
│   │       └── providers.py
│   ├── evidence/
│   │   ├── models.py
│   │   ├── evaluator.py
│   │   ├── fusion.py
│   │   └── context_builder.py
│   ├── database/
│   │   ├── postgres/
│   │   ├── neo4j/
│   │   └── qdrant/
│   ├── trace/
│   │   ├── models.py
│   │   ├── recorder.py
│   │   ├── buffer.py
│   │   ├── writer.py
│   │   └── instrumentation.py
│   ├── evaluation/
│   │   ├── datasets/
│   │   ├── metrics/
│   │   ├── golden_traces/
│   │   └── runners/
│   ├── llm/
│   │   ├── provider.py
│   │   ├── ollama.py
│   │   ├── vllm.py
│   │   └── prompts/
│   └── config/
├── langflow/
│   ├── flows/
│   └── components/
├── frontend/
│   ├── app/ or pages/
│   ├── components/
│   ├── features/
│   │   ├── discovery/
│   │   ├── conversation/
│   │   └── trace-viewer/
│   ├── lib/
│   └── styles/
├── data/
│   ├── raw/
│   ├── processed/
│   ├── benchmarks/
│   └── seeds/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── orchestration/
│   ├── agentic/
│   ├── api/
│   └── evaluation/
├── docker-compose.yml
├── .env.example
├── README.md
└── project documentation
```

## 2. Placement rules

### `backend/api/`

Transport only: routes, request/response schemas, auth dependencies, streaming adapters.

Do not choose agents here.

### `backend/state/`

Typed orchestration/session state, goals, checkpoint serialization.

### `backend/orchestrator/`

The custom harness. Action registry, eligibility, decision scoring, dispatch, parallelism, retries, recovery, termination and LangGraph construction.

### `backend/agents/`

Exactly three specialized packages: `text`, `image`, `graph`. `common/` contains shared contracts and does not count as a fourth agent.

### `backend/evidence/`

Evidence models, modality fusion, support/contradiction/gap evaluation and deterministic Final LLM context construction.

### `backend/database/`

Repositories/adapters for PostgreSQL, Neo4j and Qdrant. Keep domain policy outside DB adapters.

### `backend/trace/`

Trace event models, recorder, bounded buffer, asynchronous writer and instrumentation. This package must isolate persistence failures from the main task.

### `backend/evaluation/`

Offline benchmark execution, golden traces and metric calculation. Keep evaluation-only code out of runtime logic.

### `backend/llm/`

Provider-neutral LLM interface and local serving adapters.

### `langflow/`

Optional visual/demo artifacts and custom components. LangGraph + Python remains the execution authority.

### `frontend/`

User interface. Required feature areas: discovery, conversation, active plant context, image upload, candidate selection, streaming, optional trace viewer.

### `data/`

Reproducible source/processed/benchmark/seed data. Never store secrets.

### `tests/`

- `unit/`: deterministic logic.
- `integration/`: DB/provider/API boundaries.
- `orchestration/`: LangGraph control loop.
- `agentic/`: state-dependent behavior and multiple valid paths.
- `api/`: transport contracts.
- `evaluation/`: trace/metric correctness.

## 3. Feature placement

| Change | Primary location | Required tests |
|---|---|---|
| action/eligibility/decision | `backend/orchestrator/` | `unit/`, `orchestration/`, `agentic/` |
| text/entity capability | `backend/agents/text/` | `unit/`, `integration/` |
| image capability | `backend/agents/image/` | `unit/`, `integration/` |
| graph query | `backend/agents/graph/` | `unit/`, `integration/` |
| evidence rule | `backend/evidence/` | `unit/`, `agentic/` |
| persistence | `backend/database/` | `integration/` |
| trace event | `backend/trace/` | `unit/`, `integration/`, `evaluation/` |
| evaluation metric | `backend/evaluation/` | `evaluation/` |
| API endpoint | `backend/api/` | `api/`, plus domain tests |
| UI feature | `frontend/features/` | frontend test location chosen by scaffold |

## 4. New files

Place code in the smallest owning package. Avoid generic `utils.py` dumping grounds. Shared utilities must have a clear ownership boundary.

## 5. Nested AGENTS.md

Root `AGENTS.md` is sufficient initially.

Add `frontend/AGENTS.md` only if frontend-specific rules materially differ.

Add `backend/agents/AGENTS.md` only if all specialized agents need a stable scoped policy that should not clutter the root.

Do not create three separate agent instruction files unless genuinely necessary.
