# Repository instructions

## Mission and authority

Build and maintain IMPARK as a one-month academic demonstration for Indian medicinal-plant discovery and knowledge retrieval. The **implemented** runtime is one DeepAgents main orchestrator with exactly three specialist subagents (Text/Entity, Image Understanding, Knowledge Graph). The older deterministic action-scoring harness was removed. This file describes current repository boundaries; explicit newer user requirements take priority, then current source/tests, then the current references in `docs/`. Dated design/report files are historical when labeled.

## Current boundaries

- Every chat begins in discovery and can lock exactly one active plant. A different plant requires a new chat. Clarification resumes the same LangGraph checkpoint/lineage.
- `backend/main.py` owns dependency lifecycle; `backend/services/conversations.py` owns session/plant scope; `backend/services/runs.py` owns durable asynchronous operations/SSE; `backend/orchestrator/deepagents/` owns agent delegation and answer assembly.
- The main agent may plan/delegate only to three specialist subagents. Their tools reuse the existing text search, image classifier/vector retrieval, and typed graph retrieval. `AgentHost` is dependency/trace plumbing, not an extra planner.
- Graph queries are code-owned, allow-listed, parameterized, bounded, timed out, read-only, and scoped to the active plant. Never turn user/model text into raw Cypher.
- Retrieved evidence retains provenance and class (`traditional`, `preclinical`, `in-vitro`, `animal`, `clinical`, `mechanistic`, `established`, `unknown`). The model may explain general concepts from pretrained knowledge, but must not invent plant-specific graph facts, experiments, source URLs, treatment efficacy, dosage, or stronger evidence. Keep general context distinguishable from retrieved facts.
- PostgreSQL is durable for sessions, messages, runs/events, traces, search projection and checkpoints; Neo4j is the curated KG; Qdrant holds separate text/image vectors. Redis has an optional adapter but is not part of active startup. Do not migrate/seed/copy data automatically at web startup.
- Route handlers translate HTTP to services. Pydantic v2 contracts are in `backend/api/schemas/` and `backend/contracts/`. Do not silently change `/api/v1` or SSE semantics without updating exported frontend contracts and tests.
- `TraceRecorder` is a buffered side channel; trace persistence must not block or decide a turn. Public run SSE events are separately durable/replayable.
- Use Python 3.12+, type new code, retain async I/O, do heavy model work off the event loop, avoid broad exception swallowing, and never log secrets. Validate uploaded images and enforce size/content limits.
- Keep API keys, model tokens, database credentials and real URLs in ignored environment files. One backend process is enforced by a PostgreSQL advisory lease for the current demo; do not claim multi-worker deployment support.
- Add regression tests for behavior changes, run relevant type/lint/test checks, and update docs/decisions when behavior changes. Do not describe a proposed feature as implemented.

Current architecture, API, file map, setup, and limits: [documentation index](docs/README.md). The root `design.md` remains the frontend visual/UX specification. If a requirement conflicts with the current code, record the discrepancy explicitly before changing contracts or making a claim.
