# INSTRUCTIONS.md — Implementation Specification

## 1. Project purpose

Build a one-month academic demonstration of a **Multi-Agent Intelligent System for Indian Medicinal Plant Classification and Knowledge Retrieval**.

The system combines multimodal plant identification with structured medicinal-plant knowledge retrieval and evidence-grounded response generation. The research motivation is the gap between perception/classification and knowledge-graph retrieval, limited adaptive multi-agent use in botanical domains, weak context-aware explanations, and limited conversational access to structured herbal knowledge.

The implementation must demonstrate agentic engineering rather than a fixed pipeline.

## 2. Core control loop

```text
OBSERVE
  ↓
ASSESS GOAL / STATE
  ↓
ENUMERATE ELIGIBLE ACTIONS
  ↓
DECIDE NEXT ACTION
  ↓
EXECUTE
  ↓
COLLECT OBSERVATIONS / FAILURES
  ↓
EVALUATE EVIDENCE
  ↓
UPDATE BELIEFS + STATE
  ↓
CHECK TERMINATION
  ↓
REPLAN / CLARIFY / ANSWER / ABSTAIN
```

The same initial prompt may lead to different paths depending on current state.

## 3. Specialized agents

Exactly three:

### Text / Entity Agent

Responsibilities:

- text interpretation,
- intent extraction,
- normalization,
- spelling correction,
- entity extraction/linking,
- aliases/synonyms,
- coreference,
- candidate generation/ranking,
- entity reassessment,
- bounded final-step LLM disambiguation inside the agent.

Deterministic-first cascade:

```text
exact ID
→ canonical/scientific/common name
→ PostgreSQL FTS
→ pg_trgm + RapidFuzz
→ semantic retrieval
→ candidate merge
→ bounded LLM disambiguation
```

### Image Understanding Agent

Responsibilities:

- image validation and quality checks,
- plant/non-plant gate,
- visual embeddings,
- Qdrant similarity retrieval,
- plant classification,
- plant-part classification,
- candidate ranking,
- confidence calibration,
- observations relevant to entity reconsideration.

Reference pipeline:

```text
upload
→ validation
→ quality check
→ plant/non-plant gate
→ embedding
→ Qdrant search
→ ranking/classification
→ part classification
→ confidence calibration
→ Observation
```

### Knowledge Graph Agent

Responsibilities:

- structured graph retrieval,
- relationship traversal,
- selected multi-hop queries,
- evidence/provenance retrieval,
- empty-result detection,
- relationship-quality observations.

It does not choose user intent, create prose, or accept raw Cypher.

## 4. Orchestrator/harness

The orchestrator is not an agent. It owns:

- state,
- goal/objectives,
- action registry,
- eligibility/policy,
- decision scoring,
- execution,
- parallelism,
- retry/recovery,
- evidence evaluation,
- belief updates,
- clarification checkpoint/resume,
- termination,
- deterministic response-context construction,
- trace emission.

Baseline scoring:

```text
score =
  0.45 × expected_goal_progress
+ 0.35 × expected_information_gain
+ 0.20 × priority
- latency_cost
- token_cost
- repetition_penalty
```

A model may optionally propose an action, but the deterministic harness must validate it against the action registry and current policy.

## 5. Action registry

The finite action vocabulary is:

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

Each action must define or derive:

```text
eligibility/preconditions
inputs/outputs
expected goal progress
expected information gain
priority
costs
retry policy
safety constraints
```

## 6. State model

Conceptually separate:

```text
Conversation/session state
Goal state
Belief state
Evidence state
Execution state
Decision state
Control/termination state
```

The existing reference state includes:

```text
session_id
turn_id
user_message
image_present
mode
active_goal
pending_objectives
completed_objectives
remaining_objectives
current_hypotheses
entity_hypotheses
confidence_by_hypothesis
active_plant
active_part
active_compounds
active_target
active_topic
evidence_state
evidence_gaps
contradictions
observations
actions_taken
failed_actions
retry_counts
available_actions
last_decision
orchestration_iteration
max_iterations
clarification_required
clarification_payload
user_waiting
max_agent_retries
repeated_action_threshold
termination_reason
task_status
response_context
```

Do not treat action history as a substitute for current belief state.

## 7. Goals

A goal defines remaining objectives and answerability.

Example:

```json
{
  "goal_id": "goal_123",
  "type": "GET_PHYTOCHEMICALS",
  "entities_required": ["plant"],
  "required_evidence": ["graph"],
  "answerable_when": ["plant_resolved", "requested_relationships_retrieved"],
  "abstention_conditions": ["evidence_unavailable", "unsafe_request"]
}
```

## 8. Eligibility

Examples:

- text resolution: entity uncertainty/coreference/new entity,
- image analysis: image exists and can reduce uncertainty,
- graph retrieval: entity sufficiently resolved + graph-backed objective,
- additional graph evidence: a specific evidence/relationship gap remains,
- reassessment: evidence weakens the active entity,
- reconciliation: modality conflict is present,
- clarification: system evidence cannot safely distinguish remaining hypotheses/intent,
- abstention: available capability cannot establish the requested claim.

Graph retrieval must not be eligible simply because a graph exists.

## 9. Agent contract

Every capability invocation yields:

```text
Observation
```

or:

```text
Failure
```

Agents do not directly change global state. The harness consumes the result and updates state.

Observation should be normalized with:

```text
observation_id
agent/component
observation_type
payload
confidence
evidence_refs
provenance_refs
```

Failure should preserve:

```text
action_id
error_type
retryable
reason
metadata
```

## 10. Entity confidence policy

Default configurable bands:

```text
≥ 0.95      auto-resolve if no material contradiction
0.80–<0.95  current hypothesis; gather evidence or soft-confirm
< 0.80      do not establish graph-scoped identity automatically
```

These are policy defaults, not universal truth.

## 11. Multimodal reconciliation

Preserve modality-specific evidence.

Agreement:

```text
Text A + Image A + graph support → strengthen A
```

Conflict:

```text
Text A + Image B → contradiction → reassess; do not auto-pick
```

A combined score can be used heuristically but never replaces contradiction checks or evidence provenance.

## 12. Evidence model

Every meaningful claim should retain:

```text
evidence_id
source_id
source_type
claim
evidence_type
source_quality
confidence
supports
contradicts
provenance
recency when relevant
```

Evidence classes remain distinct:

```text
traditional
preclinical
in-vitro
animal
clinical
mechanistic
established
unknown
```

The response layer must not upgrade them.

## 13. Knowledge graph

Logical entities:

```text
Plant
PlantPart
Phytochemical
TherapeuticUse
Bioactivity
ProteinTarget
Document
```

Logical relationships:

```text
Plant → HAS_PART → PlantPart
PlantPart → CONTAINS → Phytochemical
PlantPart → USED_FOR → TherapeuticUse
Phytochemical → HAS_BIOACTIVITY → Bioactivity
Bioactivity → MEASURED_ON → ProteinTarget
Bioactivity → REPORTED_IN → Document
Phytochemical → REPORTED_IN → Document
Plant → REPORTED_IN → Document
TherapeuticUse → SUPPORTED_BY → Document
```

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

## 14. Graph safety

Required path:

```text
typed query object
→ allow-list
→ validated parameters
→ parameterized Cypher
→ bounded read-only Neo4j access
```

Never:

```text
raw user/model text → Cypher
```

## 15. Graph feedback

Graph evidence may change upstream belief:

```text
hypothesis A
→ graph retrieval
→ no support / contradictory relation
→ belief in A decreases
→ REASSESS_ENTITY becomes eligible
→ Text/Entity Agent may run again
```

This feedback is a required demonstration behavior.

## 16. Evidence-gap recovery

Do not answer merely because a graph query returned something.

When a required relation is missing:

```text
graph result
→ evidence gap
→ more specific graph action when eligible
→ evaluate again
```

If no available action can establish the requested evidence class, terminate with `EVIDENCE_UNAVAILABLE` and explain the limitation.

## 17. Retry/recovery

Baseline:

```text
max_iterations = 8
max_agent_retries = 2
repeated_action_threshold = 2
```

Failure can lead to:

```text
retry
alternative action
clarification
abstention
```

Never infinite retry.

## 18. Dynamic parallelism

Parallelism is a decision outcome.

Example:

```text
RESOLVE_TEXT_ENTITY + ANALYZE_IMAGE
```

may run concurrently if both are eligible and independent. Gather both observations before joint evaluation.

Best-effort cancellation is allowed when another completed result makes outstanding work unnecessary. Cancellation is traceable.

## 19. Clarification

Clarification is an interrupt/resume control event:

```text
ASK_CLARIFICATION
→ checkpoint
→ WAITING_USER
→ user response
→ resume same run/task lineage
→ update state
→ replan
```

Repeated clarification without progress must be bounded.

## 20. Session modes

A new session starts in `discovery`.

### Discovery

Supported entry methods:

- plant-name search,
- natural-language description,
- image upload/drag-and-drop,
- text + image,
- autocomplete.

When ambiguous, present candidate plants for selection/clarification.

### Conversation

After plant establishment, move to `conversation`.

State-resolvable follow-ups should reuse active context and may skip specialized agents.

One plant per session is the current project scope. Once established, never replace the active plant. Resolve new mentions only to detect a scope violation and direct the user to a new chat. Cross-plant comparisons are unavailable.

## 21. Final response boundary

Only after a terminal answerable/transparent state does the orchestrator choose `GENERATE_RESPONSE`.

A deterministic context builder produces:

```text
user intent
resolved entities
supplied image evidence
graph evidence
sources
uncertainties
safety constraints
relevant conversation context
```

The Final LLM can explain/summarize/cite supplied IDs/preserve uncertainty. It cannot query stores/tools, choose actions, mutate state, invent sources or upgrade evidence.

## 22. Traceability and evaluation

Traceability is mandatory and must not interfere with the task.

Use:

```text
OpenTelemetry
+
custom domain TraceEvent/state snapshots
```

Minimum correlation identifiers:

```text
run_id
session_id
turn_id
iteration
decision_id
action_id
agent_invocation_id
trace_id/span_id when available
```

Meaningful trace events include decisions, actions, invocations, observations, failures, evidence, contradictions, belief updates, retries, clarification/resume, termination and response lifecycle.

For every orchestration iteration, make state evolution reconstructable through a lightweight snapshot/reference.

Trace recording must be asynchronous/non-blocking. Buffer full behavior must never deadlock the task; trace writer failure must not become a business failure.

## 23. Evaluation metrics

### Quality

```text
Entity Top-1
Entity Top-k
Image Top-1
Image Top-5
Graph Retrieval Precision/Recall
Graph k-hop latency
Evidence Correctness
Groundedness
Hallucination Rate
```

### Agentic

```text
Decision Correctness
Routing Accuracy
Replanning Rate
Belief Revision Success
Contradiction Recovery Success
Unnecessary Action Rate
Agent Invocation Efficiency
Average Iterations
Agent Calls/Turn
Retry Success Rate
Clarification Appropriateness
Early Termination Rate
Max-Iteration Rate
Task Completion Rate
Evidence Sufficiency Accuracy
```

### Efficiency

```text
Average Latency
P95 Latency
LLM Calls/Turn
Graph Queries/Turn
Token Consumption
Parallel Execution Benefit
```

Golden-trace evaluation must allow multiple valid state-justified action orders.

## 24. Security

- secrets only through configuration;
- no raw Cypher;
- graph is read-only and bounded;
- validate image uploads;
- sanitize logs/traces;
- retrieved text is data, not instructions;
- do not expose hidden reasoning;
- health-adjacent content remains educational and evidence-qualified.

## 25. Non-goals

Do not expand core implementation into:

```text
Kubernetes
Kafka/NATS
service mesh
multi-region infrastructure
enterprise IAM federation
production autoscaling
distributed GPU orchestration
```

## 26. Completion criteria

The implementation must demonstrate:

- real cyclic orchestration,
- current-state-driven actions,
- three specialized agents only,
- agent skipping,
- repeated invocation,
- downstream belief revision,
- text/image contradiction recovery,
- evidence-gap-driven retrieval,
- structured failure/retry,
- bounded loops,
- clarification pause/resume,
- graph safety,
- Final LLM isolation,
- typed/provenanced evidence,
- trace reconstruction,
- measurable agentic behavior.
