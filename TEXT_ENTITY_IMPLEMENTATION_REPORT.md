# Text/entity implementation report — 2026-10-10

## Delivered

- Async local/cloud PostgreSQL and Qdrant interfaces, explicit migrations/provisioning, safe
  environment configuration, persistent Docker volumes and health checks.
- Actual Neo4j projection: 40 plants, 481 aliases, 521 total name records and active name vectors;
  compound/use/target name and identifier catalogs for typed reverse lookup.
- Exact/alias, FTS, trigram, spelling suggestions and multilingual semantic retrieval;
  autocomplete, candidate confirmation, intent extraction, coreference, plant switching,
  negation, scoped comparisons, reassessment and ambiguity handling.
- Stateful discovery/conversation integration, bounded actions/retries, same-lineage clarification,
  evidence provenance, contradiction/recovery behavior and grounded response rendering.
- PostgreSQL sessions/history, background domain traces and repeatable offline evaluation.

## Decision-model removal

Decision-model fallback was rejected after evaluation. At the user's request, the experimental
adapters, tests, trial scripts/results, environment settings and Docker resources were removed.
The Text Agent uses deterministic interpretation and retrieval with clarification for uncertainty.
Graph access belongs to the separate Knowledge Graph Agent, selected by the harness.

## Retrieval evaluation

The saved 24-case synthetic-prompt/real-catalog evaluation has 18 positive identity cases,
Recall@5 = 1.0, MRR = 1.0 and zero false automatic resolutions. This limited suite is not a
general accuracy estimate. All 521 source name records are separately checked for source-plant
recall in live integration tests, preserving ambiguity rather than pretending aliases are unique.

## Final validation

- `pytest -q` with local PostgreSQL/Qdrant and Neo4j integration/write opt-ins: **143 passed**
  in 42.62 seconds. Tests include parameter binding, rollback/read guards, repeated migrations,
  real embeddings, every imported name, graph retrieval, reverse lookup, comparisons,
  clarification/restart, stale-evidence prevention and safety abstention.
- Ruff: passed. Strict mypy: passed for 96 backend source files. `pip check`: passed.
- Store health: PostgreSQL and Qdrant both healthy. Repeated sync reports 40 plants, 521 names,
  `unchanged=1`. Final retrieval evaluation p50 5.705 ms, p95 278.16 ms on this local run.
- Known local secret values were checked against all changed/new deliverable files: no matches.
- Application dependencies are recorded in `requirements-dev.lock`.

## Scope and remaining limitations

The Text Agent backend is usable for the documented discovery paths. It does not understand every
possible natural-language formulation, diagnose disease, or infer plant identity reliably from
visual descriptions. It asks for clarification or abstains when supported evidence is insufficient.
Scores are conservative heuristics, not empirically calibrated probabilities.

The Image Agent and frontend UI remain separate unfinished milestones. The grounded response
component is deterministic; a generative Final LLM is not required for these retrieval responses.
Production auth, live streaming selection, external telemetry export remain deferred. PostgreSQL-backed LangGraph checkpointing and explicit
interrupted-run recovery are now implemented; see HARNESS_GUIDE.md. Cloud configuration is supported but not live-tested.

See [setup and API examples](TEXT_ENTITY_GUIDE.md), [decisions](DECISIONS.md), and the generated
change inventory `data/evaluation/changed_files.txt` for the complete modified-file list.

Final database verification: Neo4j retains 4,075 nodes and 11,697 relationships. PostgreSQL
session, trace and evaluation persistence was checked directly after the tests.

Cleanup validation: 143 tests pass after removing the seven model-specific test cases.
The experimental container, both model images and the dedicated trial model volume are removed.
> **Historical/design reference (updated 2026-10-18).** The active implementation is the DeepAgents main orchestrator with three specialist subagents, plus an outer LangGraph checkpoint/clarification adapter. This document may describe the removed deterministic harness, prior response policies, old test counts, or planned features. For current behavior use [implemented architecture](docs/architecture/README.md), [API and frontend](docs/api-and-frontend/README.md), [file map](docs/repository-map/README.md), and the source code. Do not treat historical statements below as current runtime guarantees.
