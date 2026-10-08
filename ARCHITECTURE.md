# ARCHITECTURE.md — Technical Architecture

## 1. System overview

```text
USER / FRONTEND
      ↓
FASTAPI API + STREAMING
      ↓
AGENTIC ORCHESTRATOR / HARNESS
      │
      ├── State + Goal Manager
      ├── Action Registry
      ├── Policy / Eligibility Engine
      ├── Decision Engine
      ├── Execution / Parallel Dispatcher
      ├── Evidence Evaluator
      ├── Belief Updater
      ├── Recovery / Retry
      ├── Termination
      └── Trace Recorder (side channel)
      │
      ├──────────────┬───────────────┐
      ↓              ↓               ↓
TEXT/ENTITY     IMAGE             KNOWLEDGE
AGENT           AGENT             GRAPH AGENT
      ↓              ↓               ↓
PostgreSQL       Qdrant            Neo4j
      │              │               │
      └──────────────┴───────────────┘
                     ↓
             Evidence / State Update
                     ↓
              Terminal decision
                     ↓
          Deterministic Context Builder
                     ↓
                 Final LLM
                     ↓
                 Stream Answer
```

## 2. Core control loop

```text
OBSERVE
  ↓
ASSESS GOAL/STATE
  ↓
ENUMERATE ACTIONS
  ↓
POLICY FILTER
  ↓
DECIDE
  ↓
DISPATCH
  ↓
OBSERVE
  ↓
EVALUATE EVIDENCE
  ↓
UPDATE BELIEFS/STATE
  ↓
TERMINATION CHECK
  ├─ CONTINUE → REPLAN
  ├─ CLARIFY → CHECKPOINT / WAIT
  ├─ ANSWER → CONTEXT BUILDER / FINAL LLM
  └─ ABSTAIN/FAIL → TERMINAL STATE
```

## 3. Major responsibilities

### Frontend

Owns discovery UI, conversation UI, image upload, candidate selection, streaming presentation, active context, and optional trace/evaluation viewer.

It does not make orchestration decisions.

### FastAPI

Owns request validation, session/turn transport, authentication hooks, streaming and safe errors. It calls the orchestrator rather than selecting agents directly.

### Orchestrator/harness

Owns the control loop and is the final authority on action eligibility, selection, safety, retries and termination.

### Three agents

- Text/Entity: language/entity resolution.
- Image: visual identification/retrieval.
- Knowledge Graph: typed Neo4j retrieval/evidence.

### Final LLM

Only natural-language generation from supplied `response_context`.

## 4. LangGraph role

LangGraph provides:

- state propagation,
- cyclic execution,
- conditional routing,
- checkpointing,
- interrupt/resume.

Python modules contain business/control logic. Do not make giant LangGraph nodes that hide policy.

## 5. Action architecture

Bounded actions:

```text
RESOLVE_TEXT_ENTITY
ANALYZE_IMAGE
RETRIEVE_GRAPH
RETRIEVE_ADDITIONAL_GRAPH_EVIDENCE
REASSESS_ENTITY
RECONCILE_MODALITIES
UPDATE_CONTEXT
RETRY_ACTION
ASK_CLARIFICATION
ABSTAIN
GENERATE_RESPONSE
COMPLETE
```

Action metadata includes eligibility, inputs/outputs, information gain, goal progress, costs, retry rules and safety constraints.

## 6. Decision architecture

Default score:

```text
0.45 * goal_progress
+0.35 * information_gain
+0.20 * priority
-latency_cost
-token_cost
-repetition_penalty
```

Model-assisted suggestions are optional and constrained to predeclared actions. Deterministic policy validates the suggestion.

## 7. State architecture

Conceptual state groups:

```text
Goal
Belief/Hypotheses
Evidence/Provenance
Execution/History
Decision
Control/Termination
Conversation Context
```

Current active context can include:

```text
active_plant
active_part
active_compounds
active_target
active_topic
```

## 8. Discovery/conversation lifecycle

```text
NEW SESSION
     ↓
DISCOVERY
     ├─ search/name/NL text
     ├─ image
     └─ text + image
     ↓
resolution + fusion
     ↓
confidence gate
     ├─ ambiguous → candidates/clarification → discovery
     └─ resolved → active context
                         ↓
                    CONVERSATION
                         ├─ reuse state when unambiguous
                         ├─ new image → image agent if useful
                         └─ new plant → inline resolution
```

There is one runtime; discovery is not a separate service.

## 9. Text/Entity pipeline

```text
input
 ↓
normalize
 ↓
exact/canonical/scientific/alias
 ↓
PostgreSQL FTS
 ↓
pg_trgm + RapidFuzz
 ↓
semantic retrieval
 ↓
merge/rank
 ↓
bounded LLM disambiguation
 ↓
Observation
```

## 10. Image pipeline

```text
image
 ↓
validation
 ↓
quality check
 ↓
plant/non-plant gate
 ↓
embedding
 ↓
Qdrant ANN retrieval
 ↓
candidate ranking/classification
 ↓
plant-part classification
 ↓
confidence calibration
 ↓
Observation
```

PyTorch, OpenCV, Pillow, Transformers and CLIP/DINOv2-family models are supported by the design. Exact model is a decision item.

## 11. Graph pipeline

```text
orchestrator
 ↓
typed query object
 ↓
allow-list
 ↓
parameter validation
 ↓
parameterized Cypher
 ↓
Neo4j read-only
 ↓
bounded result
 ↓
Observation + evidence/provenance
```

Graph entities:

```text
Plant, PlantPart, Phytochemical, TherapeuticUse,
Bioactivity, ProteinTarget, Document
```

## 12. Evidence and belief feedback

```text
Observation
 ↓
normalize
 ↓
provenance
 ↓
support / contradiction / gap
 ↓
belief update
 ↓
new eligible actions
```

Required feedback examples:

```text
Graph contradiction → entity reassessment
Text/image conflict → reconciliation → reassessment
Evidence gap → additional graph retrieval
```

## 13. Final response boundary

```text
terminal state
 ↓
GENERATE_RESPONSE
 ↓
deterministic response_context
 ↓
Final LLM
 ↓
stream response
```

The Final LLM has no datastore/tool access and cannot add facts to the context.

## 14. Clarification architecture

```text
ASK_CLARIFICATION
 ↓
checkpoint
 ↓
WAITING_USER
 ↓
resume same run/task lineage
 ↓
observe new turn
 ↓
update goal/belief
 ↓
replan
```

## 15. Recovery and termination

Failures become structured observations. Recovery options:

```text
retry
alternative action
clarification
abstention
```

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

## 16. Storage topology

```text
                 APPLICATION
                     │
       ┌─────────────┼─────────────┐
       ↓             ↓             ↓
 PostgreSQL        Redis          Neo4j
 durable           transient      graph
 app/evidence/     cache          relationships
 trace/eval
                     │
                     ↓
                   Qdrant
                visual vectors
```

## 17. Observability architecture

```text
Orchestrator / Agents / API
          │
          ├────────────→ OpenTelemetry → metrics/traces
          │
          └────────────→ Domain Trace Recorder
                               ↓
                         bounded async buffer
                               ↓
                         background writer
                               ↓
                          PostgreSQL
                               ↓
                       Evaluation Engine
```

The trace subsystem is a side channel. It records behavior without participating in action choice or task success.

## 18. Trace model

Trace events correlate:

```text
run_id
session_id
turn_id
iteration
decision_id
action_id
agent_invocation_id
trace_id/span_id
```

A domain event can contain sanitized input/output snapshots, state snapshot references, timing, status, evidence refs and provenance refs.

## 19. Dynamic parallelism

Parallel execution is selected only when independent actions are both useful/eligible.

Example:

```text
Decision
 ├─ Text/Entity Agent
 └─ Image Agent
       ↓
collect
       ↓
evaluate together
```

Best-effort cancellation is allowed when another result makes outstanding work unnecessary. Cancellation must be traced.

## 20. Deployment

Primary development/demo topology:

```text
Docker Compose
├── FastAPI application
├── frontend
├── PostgreSQL
├── Redis
├── Neo4j
├── Qdrant
├── Ollama/model service as configured
├── OpenTelemetry Collector if used
├── Prometheus
└── Grafana
```

Kubernetes is future work.

## 21. Anti-patterns

Never introduce:

- fixed classify → retrieve → explain flow hidden behind conditionals,
- fourth specialized agent,
- unrestricted planner LLM,
- raw user/model Cypher,
- Final LLM datastore access,
- unbounded retries,
- synchronous trace writes on the critical path,
- new session for clarification,
- rerun every agent on every turn,
- evidence inflation,
- production infrastructure unrelated to the research demonstration.
