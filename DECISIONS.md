# DECISIONS.md — Architecture Decision Record

This file records established decisions and explicitly unresolved decisions. Do not turn a TODO into a permanent architecture without updating this file.

## D-001 — One-month academic scope

**Decision:** Treat the system as an academic demonstration, not a production platform.

**Context:** The project is intended to demonstrate agentic engineering and research behavior.

**Reason:** Control loop, state/belief, evidence, multimodal feedback, grounding and evaluation are the core contribution.

**Alternatives:** Production-grade distributed infrastructure.

**Consequences:** Docker Compose is enough; Kubernetes/Kafka/NATS/service mesh/multi-region are future work.

## D-002 — Exactly three specialized agents

**Decision:** Only Text/Entity, Image Understanding and Knowledge Graph agents exist.

**Reason:** Preserves clear capability boundaries and the research framing.

**Alternatives:** planner/executor/critic or extra safety agents.

**Consequences:** orchestration, evidence, recovery and termination remain harness components.

## D-003 — Orchestrator is a deterministic/custom harness

**Decision:** The orchestrator is a Python control plane around LangGraph, not a fourth agent.

**Reason:** It must be auditable and authoritative for policy, budgets, safety and termination.

## D-004 — Deterministic action selection baseline

**Decision:** Use eligible-action scoring with goal progress, information gain, priority and costs/repetition penalty.

**Reason:** Reproducible and easy to evaluate.

**Alternatives:** unrestricted planner LLM/RL.

**Consequences:** model suggestions are optional and subordinate to validation.

## D-005 — Finite action registry

**Decision:** Use the bounded action vocabulary in `INSTRUCTIONS.md`.

**Reason:** Safety, auditability and loop bounds.

## D-006 — LangGraph for cyclic runtime

**Decision:** LangGraph handles stateful cycles, conditional routing and checkpoint/interrupt-resume.

**Reason:** matches required architecture.

**Consequences:** Python modules contain detailed policy/logic; LangGraph nodes remain thin.

## D-007 — Final LLM hard boundary

**Decision:** Final LLM receives only deterministic `response_context`; no direct datastore/tool access.

**Reason:** evidence grounding and health-adjacent safety.

## D-008 — Typed evidence/provenance

**Decision:** Preserve evidence class, source/provenance, confidence, support/contradiction and gaps.

**Reason:** final generation must not inflate scientific/medical certainty.

## D-009 — Safe Neo4j access

**Decision:** typed allow-listed query objects, validated parameters, parameterized Cypher, bounded results/timeouts and read-only credentials.

**Reason:** security and reproducibility.

## D-010 — One runtime, two modes

**Decision:** each new session starts in `discovery`; successful plant establishment switches to `conversation`.

**Reason:** plant context should be established before unrestricted follow-up.

## D-011 — Clarification is interrupt/resume

**Decision:** clarification checkpoints and resumes the same run/task lineage.

**Reason:** user correction should update the existing state rather than start over.

## D-012 — Dynamic parallelism

**Decision:** parallel execution is selected only when independent actions are both useful and eligible.

**Reason:** concurrency without always running every agent.

## D-013 — Deterministic-first entity resolution

**Decision:** exact → canonical/scientific/alias → FTS → `pg_trgm`/RapidFuzz → semantic → bounded LLM escalation.

**Reason:** lower cost and stronger determinism.

## D-014 — PostgreSQL durable application/evaluation store

**Decision:** PostgreSQL stores durable session/orchestration/evidence/trace/evaluation data.

## D-015 — Redis transient/cache/coordination

**Decision:** Redis is not the durable authority.

## D-016 — Neo4j knowledge graph

**Decision:** Neo4j stores plant/part/compound/use/bioactivity/target/document relationships and supports bounded multi-hop retrieval.

## D-017 — Qdrant visual retrieval

**Decision:** Qdrant stores/retrieves image embeddings and candidate vectors.

## D-018 — Provider-neutral LLM interface

**Decision:** abstract LLM access behind `LLMProvider`; local Ollama and optional vLLM are supported paths.

## D-019 — OpenTelemetry + custom domain trace

**Decision:** OpenTelemetry captures technical telemetry; custom events/snapshots capture agentic behavior such as decision, evidence, belief, contradiction and termination.

## D-020 — Trace side channel is non-blocking

**Decision:** trace events are enqueued to a bounded async buffer and persisted by background writers; trace failures never fail the main task.

**Reason:** traceability is mandatory but must not interfere with task execution.

## D-021 — Iteration snapshots

**Decision:** make per-iteration state evolution reconstructable.

**Reason:** enables behavioral evaluation and paper evidence.

## D-022 — Golden traces evaluate valid paths, not exact sequence

**Decision:** multiple state-justified action orders are acceptable.

**Reason:** adaptive agentic systems need not follow one path.

## D-023 — Docker Compose

**Decision:** use Compose as the primary development/demo topology.

## D-024 — Educational/health-adjacent boundary

**Decision:** preserve evidence classes/uncertainty and avoid unsupported dosage/treatment claims.

## D-025 — Langflow is optional visual support

**Decision:** LangGraph + Python is the execution authority; Langflow may support visual flows/components/demos.

## Unresolved decisions

### R-001 — Frontend framework/version

**Status:** `TODO / DECISION REQUIRED`

React/Next.js is the stated stack family; choose the exact framework/version and package manager.

### R-002 — Authentication/authorization

**Status:** `TODO / DECISION REQUIRED`

Choose the authentication mechanism, identity model and roles/permissions.

### R-003 — Primary streaming transport

**Status:** `TODO / DECISION REQUIRED`

Choose SSE, WebSockets, or a documented combination.

### R-004 — Public API route/version contract

**Status:** `TODO / DECISION REQUIRED`

Freeze endpoint paths, status codes and error envelope once implemented.

### R-005 — PostgreSQL migration tool and physical schema

**Status:** `TODO / DECISION REQUIRED`

Logical domains are established; exact tables/indexes/migration tooling must be finalized against the scaffold.

### R-006 — Exact LLM model

**Status:** `TODO / DECISION REQUIRED`

Choose after hardware/quality benchmarking.

### R-007 — Meaning of “open JEV models”

**Status:** `TODO / DECISION REQUIRED`

The supplied technology list uses this term without defining it. Clarify before treating it as a dependency.

### R-008 — Exact image classifier/embedding backbone

**Status:** `TODO / DECISION REQUIRED`

Choose from supported PyTorch/Transformers/CLIP/DINOv2-family options after benchmarking.

### R-009 — Qdrant collection/vector schema

**Status:** `TODO / DECISION REQUIRED`

Finalize dimensions, metric, payload and collection naming after model selection.

### R-010 — Graph ingestion/source dataset

**Status:** `TODO / DECISION REQUIRED`

Finalize dataset version, provenance, ingestion pipeline and completeness assumptions.

### R-011 — Confidence threshold calibration

**Status:** `TODO / DECISION REQUIRED`

Use supplied confidence bands as initial policy defaults; calibrate on validation data.

### R-012 — Trace privacy/retention policy

**Status:** `TODO / DECISION REQUIRED`

Decide raw vs redacted/reference storage, retention, deletion and access rules.

### R-013 — Trace buffer/degradation policy

**Status:** `TODO / DECISION REQUIRED`

Choose buffer size, overflow behavior, retry policy, shutdown flush and degraded-trace metrics.

### R-014 — Benchmark/golden-trace data format

**Status:** `TODO / DECISION REQUIRED`

Define exact record schema and expected behavioral constraints.

### R-015 — Trace/evaluation viewer access model

**Status:** `TODO / DECISION REQUIRED`

Define who can inspect runs and which fields must be redacted.

## Decision update rule

## Foundation implementation notes — 2026-10-08

These are reversible phase-one implementation choices, not resolution of the open public contracts:

- Packaging uses setuptools/pyproject + pip; pytest/pytest-asyncio, Ruff and strict mypy validate it.
- Central cross-module contracts live in `backend/contracts/`; state and goal models retain their
  documented owning packages. `backend/services/` separates transport from the harness.
- `/health` is liveness. `/dev/*` routes are opt-in development-only integration scaffolding;
  public route/version/error decisions R-004 remain unresolved. R-002 auth is fail-closed outside
  the explicit local development bypass. No deployment authentication is claimed.
- Development uses in-memory repositories/checkpoints, one worker, no startup schema mutation.
  Durable PostgreSQL adapters/migrations and horizontal deployment remain R-005.
- Trace prototype: 1024-entry bounded queue, drop-newest overflow counter, failure counter,
  one background writer, one-second best-effort shutdown flush. No persistence retry in prototype.
  R-013 remains TODO for benchmark policy; trace loss must disqualify a completeness claim.
- Snapshot fields use IDs/control flags/confidence, excluding raw prompts/image bytes/documents.
  R-012 retention/access decisions remain unresolved. Event vocabulary uses lower-case values
  consistently with the explicit phase-one prompt; DATABASE.md upper-case names are conceptual.
- The explicit phase-one prompt takes precedence over the image-pipeline illustrations:
  pretrained/custom CNN inference is the intended classification path; vector retrieval is an
  internal future stage. Exact model and schema remain R-008/R-009.
- Runtime dependencies are limited to FastAPI, Uvicorn, Pydantic/settings, LangGraph (which brings
  LangChain Core), Pillow for safe decoding, and OpenTelemetry API. No model/database driver yet.

### R-016 — Upload limits and storage lifecycle

**Status:** `TODO / DECISION REQUIRED`

Prototype accepts PNG/JPEG/WebP up to 5 MiB, 8192 pixels per dimension and 16 million total pixels.
Configuration may lower these caps. Bytes are decoded off-loop and discarded after validation;
only session-scoped metadata is retained. Decide durable blob storage, expiry, cleanup and final
limits before enabling CNN inference.

### R-017 — Goal interpretation and follow-up integration

**Status:** `TODO / DECISION REQUIRED`

The local chat scaffold creates a discovery objective. Typed domain callers/tests may supply graph
objectives. Define the Text/Entity intent observation and mapping to objectives before claiming
general conversation, new-plant switching, or state-resolved coreference in the public chat API.
Contradictions remain unresolved until explicit supported evidence/confirmation resolves them;
foundation reconciliation never silently chooses a modality.

### R-018 — Final prose validation

**Status:** `TODO / DECISION REQUIRED`

Placeholder generation cannot invent clinical claims. The harness validates supplied citation IDs,
but arbitrary future LLM prose requires a deterministic claim/evidence validation policy before
deployment. Do not mistake provider isolation or a prompt for semantic evidence-strength checking.

## Decision update procedure

### D-026 — Shared Neo4j connection and verified physical schema (2026-10-09)

**Decision:** Use the official async Neo4j driver with one pool per application lifespan, explicit
session/transaction scope, python-dotenv configuration, parameterized trusted queries and a separate
typed read-only medicinal repository. Four connection environment variables select local or Aura.

**Authority:** Explicit user request and the revised neo4j_database_design.md inventory. Live local
inspection: Community 2026.09.0, two LOOKUP indexes, no constraints; no production metadata assumed.

**Safety:** Writes require NEO4J_ALLOW_WRITES; user/agent input never becomes a query. Read operations
use server EXPLAIN classification and reject non-read statements. No startup schema/seed operation,
no APOC, no implicit retries; orchestration retains its retry authority. Neo4j enablement is explicit
to preserve the foundation's offline mode. Enabled startup validates every required setting.

**Scope:** New repositories use verified labels/properties/directions. The Graph Agent's existing
Observation adapter remains a placeholder; no medicinal evidence strength is fabricated. PostgreSQL
and full Text/Entity work from the interrupted earlier request are outside this focused change.

**Validation:** Local unit/integration tests include dictionary/single/scalar reads, parameterization,
all domain query templates, atomic writes, rollback, cancellation, limits, safe errors and lifecycle.
Aura credentials were not provided; compatibility is configuration/API-based, not a claimed live test.

## Decision update checklist

When a TODO is resolved:

1. add the decision and date,
2. update architecture/API/database/security docs,
3. remove contradictions,
4. update tests/tasks.

## Text discovery decisions - 2026-10-10

- PostgreSQL FTS (`simple`), pg_trgm and RapidFuzz precede multilingual MiniLM name vectors.
  Source alias metadata is preserved. Fuzzy/semantic scores cannot auto-establish identity.
- Import stages a generation, verifies vector count, then activates it. Neo4j stays read-only.
- Decision-model fallback was rejected after evaluation and all experimental adapters/tests/model
  artifacts removed at the user's request. This supersedes earlier final-step LLM disambiguation
  plans. Clarification is the fallback.
- Typed reverse queries and comparisons of two plants are bounded by existing budgets.
  Multiple plant-part scopes require clarification. Arbitrary multilingual intents remain limited.
- Grounded deterministic rendering preserves evidence class and provenance.
- PostgreSQL persists domain state/traces. LangGraph checkpointing remains in memory; waiting-user
  restart recovery is supported. Mid-action crash recovery and multi-worker execution remain
  TODO / DECISION REQUIRED. Image/frontend/public auth milestones are outside this delivery.

## Harness hardening update - 2026-10-10

This supersedes the earlier in-memory checkpoint limitation: configured text deployments now use
the official PostgreSQL checkpointer with explicit migration and explicit interrupted-run resume.
Pure control steps share checkpoint boundaries while dispatch remains durable. Old node aliases
remain for checkpoint compatibility. Execution is at-least-once and agents must be read-only or
idempotent. Single-worker ownership, image blob storage and distributed locking limitations are
explicit in HARNESS_GUIDE.md. Typed AgentOverrides supports teammate capability injection.

## 2026-10-10 — Single-plant scope and complete bounded Graph Agent

Explicit user clarification supersedes earlier inline-switching and cross-plant comparison decisions:
a session establishes exactly one plant, then locks it. Other plants require a new chat. API responses
include a frontend-facing notice; conflicting selections return 409 and other-plant observations
terminate with SCOPE_REJECTED. Discovery graph objectives must wait for plant identity.

The Graph Agent implements 13 static Neo4j retrieval types plus citation tracing; COMPARE_PLANTS
is deliberately policy-rejected. Reverse query names remain only as active-plant membership queries.
Evidence includes actual path nodes, branch endpoints, source URLs and stable citations. Empty
results are terminal gaps, result limits are disclosed, and property conflicts are data-quality
contradictions rather than identity or clinical contradictions. No evidence class is inferred.
Recent citation snapshots are bounded to 100 and persisted in existing session JSON; no SQL migration.
See GRAPH_AGENT_GUIDE.md for exact capabilities, tests and limitations.
