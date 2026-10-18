# End-to-end backend and agent audit — 2026-10-15

The local academic MVP runs Text/Entity, Image Understanding and Knowledge Graph agents through
the bounded LangGraph harness and versioned chat API. API routes translate requests, while the
harness chooses eligible actions and reduces typed agent observations. The active plant locks to
one species per chat; ambiguous or conflicting inputs clarify on the same run lineage. The graph
agent uses only plant-scoped, typed, bounded read queries. The response model receives deterministic
evidence context and cannot query stores or invent citations. SSE events, chat messages, evidence
snapshots and operations persist in PostgreSQL. Domain traces enqueue independently.

The full **safe local integration sweep** passed **332 tests; two Neo4j write-only tests were
skipped**. It included local PostgreSQL, Qdrant, Neo4j, the supplied CNN, real Ollama, all typed
graph query kinds, catalog aliases, discovery/conversation flows, citations, SSE replay,
cancellation, idempotency, image/text agreement and disagreement, clarification replacement,
checkpoint recovery, auth/CORS, and safety/scope handling. Five frontend SSE client tests passed.
Ruff lint/format, mypy and `pip check` passed. Results are in
`data/evaluation/full_integration_audit.xml`.

Two flow gaps were found and fixed during this audit. A combined text+image discovery request now
has a live regression proving its first question reaches graph retrieval and includes separate
image and graph evidence. A failed background SSE event writer previously could strand an
operation in `running`; its failure path now directly finalizes the operation as `failed` when
PostgreSQL remains available, with a live regression. A local real-Ollama regression verifies
graph evidence, exact citation IDs and replayed SSE text. The offline trace audit checks decision
eligibility, agent start/completion balance, response-context ordering and recorder loss, without
requiring a single prescribed action sequence.

Measured local performance after startup (three in-process HTTP runs per flow, grounded response):

| Flow | Median | Range |
|---|---:|---:|
| Text → graph answer | 852 ms | 614–2,849 ms |
| Image → discovery suggestions | 755 ms | 687–782 ms |
| Text + image → graph answer | 1,382 ms | 1,375–1,454 ms |

The synthetic harness loop measured 29 ms median with memory checkpoints and 84 ms with
PostgreSQL checkpoints over ten runs each; no trace drops or write failures occurred. These are
local single-worker measurements, not throughput or cloud guarantees. Application startup and
Ollama generation are excluded from the flow table; the separate real-Ollama integration passed.
The text retrieval evaluation on 24 synthetic prompts against the imported catalog achieved
Recall@5 1.0 for 18 positive cases, MRR 1.0 and zero false automatic resolutions, with 3.5 ms
median and 275.6 ms p95. This suite is too small to establish general natural-language accuracy.
See `data/evaluation/live_flow_audit.json`, `harness_audit_*.json`, and
`text_discovery_report.json` for raw results.

**Accuracy and deployment limits:** The image model covers 40 leaf classes. Its comparison split
uses supplied training-derived photos; independent species, non-plant, plant-part and image-shift
accuracy are unmeasured. Image ranking scores are not calibrated. Arbitrary descriptions beyond
indexed names/aliases and supported intents are not guaranteed. Neo4j write tests, cloud database
switching, distributed multi-worker locking, load testing and a curated research-grade golden-trace
corpus were not validated. The supported deployment is a single-user, single-worker academic demo,
not a clinical or production-scale service. Those limits should remain visible in frontend copy
and evaluation claims.
> **Historical/design reference (updated 2026-10-18).** The active implementation is the DeepAgents main orchestrator with three specialist subagents, plus an outer LangGraph checkpoint/clarification adapter. This document may describe the removed deterministic harness, prior response policies, old test counts, or planned features. For current behavior use [implemented architecture](docs/architecture/README.md), [API and frontend](docs/api-and-frontend/README.md), [file map](docs/repository-map/README.md), and the source code. Do not treat historical statements below as current runtime guarantees.
