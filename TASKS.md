# TASKS.md — Incremental Implementation Roadmap

## 1. Execution order

Build from control-plane foundations outward.

```text
Foundation
→ state/contracts
→ decision/action system
→ trace side channel
→ LangGraph loop
→ Text/Entity + Graph
→ recovery/evidence feedback
→ Image + multimodal fusion
→ Final LLM
→ API/streaming
→ UI
→ evaluation
→ security hardening/demo
```

Do not start with UI polish or model optimization before M1/M2 work.

## 2. F0 — Foundation

| ID | Task | Dependencies | Main files | Acceptance | Tests |
|---|---|---|---|---|---|
| F0-01 | Bootstrap repository | none | root, `backend/`, `frontend/`, config | target structure exists; imports/config load | smoke |
| F0-02 | Compose services | F0-01 | `docker-compose.yml` | PostgreSQL/Redis/Neo4j/Qdrant reachable | service smoke |

## 3. F1 — Domain state/contracts

| ID | Task | Dependencies | Main files | Acceptance | Tests |
|---|---|---|---|---|---|
| F1-01 | Typed `ConversationState` + goals | F0-01 | `backend/state/` | discovery/conversation + goal/belief/evidence/execution/decision/control represented | unit |
| F1-02 | Observation/Failure contracts | F1-01 | `backend/agents/common/` | all agents return typed `Observation | Failure` | unit |
| F1-03 | PostgreSQL persistence skeleton | F0-02, F1-01 | `backend/database/postgres/` | session/turn/state/evidence persistence works | integration |

## 4. F2 — Action/decision core

| ID | Task | Dependencies | Main files | Acceptance | Tests |
|---|---|---|---|---|---|
| F2-01 | Action registry | F1-01 | `backend/orchestrator/actions.py` | finite bounded action set + metadata | unit |
| F2-02 | Eligibility/policy engine | F2-01 | `policy.py` | ineligible actions cannot be selected | unit/agentic |
| F2-03 | Deterministic decision engine | F2-02 | `decision.py` | state-derived action scoring/selection | unit/agentic |
| F2-04 | Budget/loop guard | F2-03 | `policy.py`, `recovery.py` | bounded retries/iterations/repetition | unit/orchestration |

Baseline policy:

```text
0.45 × goal progress
+ 0.35 × information gain
+ 0.20 × priority
− latency cost
− token cost
− repetition penalty
```

Baseline budgets:

```text
max_iterations = 8
max_agent_retries = 2
repeated_action_threshold = 2
```

## 5. F3 — Traceability side channel (mandatory early)

This is a cross-cutting subsystem. It must be implemented before large agentic behavior so every later behavior is observable.

| ID | Task | Dependencies | Main files | Acceptance | Tests |
|---|---|---|---|---|---|
| F3-01 | `TraceEvent` domain model | F1-01/F1-02 | `backend/trace/` | correlation + event/status/evidence fields | unit |
| F3-02 | Async non-blocking recorder/buffer | F3-01 | `recorder.py`, `buffer.py` | caller enqueues and continues | concurrency |
| F3-03 | Background PostgreSQL writer | F3-02/F1-03 | `writer.py` | eventual persistence; writer failure isolated | integration/failure |
| F3-04 | Iteration state snapshots | F3-03 | `instrumentation.py` | state evolution reconstructable | evaluation |
| F3-05 | OpenTelemetry | F3-01 | `instrumentation.py` | technical traces/correlation/latency | integration |

### Trace invariant

```text
business operation
→ emit/enqueue trace event
→ continue business operation
→ writer persists asynchronously
```

Never:

```text
business operation → wait for trace DB write → continue
```

Trace sink failures must never fail the main task.

## 6. F4 — LangGraph control loop

| ID | Task | Dependencies | Main files | Acceptance | Tests |
|---|---|---|---|---|---|
| F4-01 | LangGraph graph | F2-03/F3-02/F1-01 | `orchestrator/graph.py` | real cycle + conditional routes | orchestration |
| F4-02 | Execution/dispatch manager | F4-01/F1-02 | `execution.py` | selected action invokes proper capability | orchestration |
| F4-03 | Observe/evaluate/update loop | F4-02 | `evidence/`, `state/` | observation can change next action | agentic |

Required cycle:

```text
observe → assess → enumerate → decide → execute → observe
→ evaluate evidence → update state/belief → terminate/replan
```

## 7. F5 — Text/Entity Agent

| ID | Task | Dependencies | Acceptance |
|---|---|---|---|
| F5-01 | Exact/canonical/scientific/alias lookup | F1-03 | deterministic entity lookup works |
| F5-02 | FTS + `pg_trgm` + RapidFuzz | F5-01 | ranked fuzzy candidates |
| F5-03 | Semantic + bounded LLM escalation | F5-02 | model call only after cheaper paths |
| F5-04 | Intent/coreference | F5-03/F1-01 | follow-ups can reuse active context |

Default confidence bands:

```text
≥ 0.95 → auto-resolve when no material contradiction
0.80–<0.95 → current hypothesis; gather evidence/soft confirm
< 0.80 → do not establish graph-scoped identity automatically
```

## 8. F6 — Knowledge Graph Agent

| ID | Task | Dependencies | Acceptance |
|---|---|---|---|
| F6-01 | Neo4j read-only adapter | F0-02 | graph connectivity works |
| F6-02 | Typed query registry/validator | F2-01/F6-01 | only allow-listed query types reach DB |
| F6-03 | Core query implementations | F6-02 | plant/parts/compounds/uses/bioactivity/targets/evidence work on fixtures |
| F6-04 | Evidence gap/feedback | F6-03/F4-03 | partial/empty result changes control decision |

Supported query vocabulary:

```text
GET_PLANT_DETAILS
GET_PLANT_PARTS
GET_PLANT_PART_DETAILS
GET_PHYTOCHEMICALS
GET_PHYTOCHEMICAL_DETAILS
GET_BIOACTIVITY
GET_PROTEIN_TARGETS
GET_THERAPEUTIC_USES
GET_DOCUMENTS
GET_EVIDENCE
GET_PLANTS_CONTAINING_COMPOUND
GET_COMPOUNDS_TARGETING_PROTEIN
GET_PLANTS_FOR_THERAPEUTIC_USE
COMPARE_PLANTS
TRACE_EVIDENCE
```

## 9. F7 — Recovery/termination/clarification

| ID | Task | Dependencies | Acceptance |
|---|---|---|---|
| F7-01 | Retry manager | F4-02 | bounded transient retry |
| F7-02 | Contradiction/reassessment | F4-03/F5-03/F6-04 | downstream evidence weakens earlier belief and can re-run Text/Entity |
| F7-03 | Checkpoint + clarification | F4-01 | pause/resume same lineage |
| F7-04 | Formal termination | F7-01/F7-03 | explicit terminal states |

Terminal states:

```text
COMPLETE
ABSTAINED
WAITING_USER
FAILED
MAX_ITERATIONS_REACHED
EVIDENCE_UNAVAILABLE
SAFETY_ABSTENTION
```

## 10. F8 — Image Understanding Agent

| ID | Task | Dependencies | Acceptance |
|---|---|---|---|
| F8-01 | Image validation/quality gate | F1-02 | invalid/non-plant input handled structurally |
| F8-02 | Embedding + Qdrant | F0-02/F8-01 | ranked visual candidates |
| F8-03 | Plant/part classification | F8-02 | typed candidate/part observations |
| F8-04 | Multimodal fusion | F8-03/F5-03/F4-03 | agreement/conflict handled explicitly |

Exact image model is a decision item.

## 11. F9 — Final response

| ID | Task | Dependencies | Acceptance |
|---|---|---|---|
| F9-01 | Deterministic response context | F6-04/F7-04 | only terminal answerable/transparent state builds context |
| F9-02 | Provider-neutral Final LLM | F9-01 | no datastore/tool access |
| F9-03 | Streaming | F9-02 | response streams through selected transport |

## 12. F10 — API

| ID | Task | Dependencies | Acceptance |
|---|---|---|---|
| F10-01 | Session/turn API | F4-01/F9-03 | discovery and conversation use one runtime |
| F10-02 | Clarification resume | F7-03/F10-01 | same state/task lineage resumes |
| F10-03 | Trace/evaluation reads | F3-03/F3-04 | safe research viewer access |

Exact endpoint paths/auth/primary stream protocol require final decisions.

## 13. F11 — Frontend

| ID | Task | Dependencies | Acceptance |
|---|---|---|---|
| F11-01 | Discovery UI | F10-01 | name/NL/image/text+image/autocomplete/candidate selection |
| F11-02 | Conversation UI | F11-01 | active context/follow-up/image/streaming/clarification |
| F11-03 | Trace viewer | F10-03 | reviewer can reconstruct run behavior |

## 14. F12 — Evaluation

| ID | Task | Dependencies | Acceptance |
|---|---|---|---|
| F12-01 | Benchmark dataset | F5/F6/F8 | text/image/graph/ambiguity/contradiction/gap cases |
| F12-02 | Golden trace format | F3-04/F12-01 | multiple valid paths accepted |
| F12-03 | Metrics engine | F12-02 | quality + agentic + efficiency metrics |
| F12-04 | Adversarial/safety cases | F12-03 | graph injection, unsupported evidence, trace outage, loops |

## 15. F13 — Security hardening

**Dependencies:** core runtime/API complete.

Acceptance:

- authentication/authorization implemented according to final decision,
- CORS restricted/configured,
- secrets absent from source/logs/traces,
- upload limits enforced,
- graph permissions read-only,
- error messages safe,
- trace privacy policy enforced.

## 16. F14 — Demo/paper preparation

**Dependencies:** benchmark/evaluation stable.

Deliver:

- README setup/run instructions,
- final architecture diagrams,
- benchmark results,
- trace viewer examples,
- evaluation tables/plots,
- limitations/future work,
- evidence of agentic behavior for paper/viva.

## 17. Milestones

### M1 — Agentic skeleton

Requires:

- state,
- actions,
- policy,
- deterministic decision engine,
- LangGraph cycle,
- trace side channel.

### M2 — Text + Graph closed loop

Demonstrate:

```text
text/entity → graph → evidence → belief update → replan/answer
```

### M3 — Multimodal agentic behavior

Demonstrate:

```text
text + image → contradiction → reconciliation → reassessment
```

Also show an agent being skipped and later invoked again.

### M4 — Demonstration/evaluation

Demonstrate:

- discovery → conversation,
- clarification/resume,
- evidence-gap recovery,
- trace viewer,
- metrics.

## 18. Rules

Do not implement later-phase complexity early unless required to unlock the current milestone. Do not replace the deterministic harness with a planner agent. Do not make trace persistence a synchronous dependency.
