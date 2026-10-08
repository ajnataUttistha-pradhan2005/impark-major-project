# TESTING.md — Testing and Evaluation Strategy

## 1. Goal

Testing must validate both:

- answer/retrieval correctness, and
- true agentic behavior of the stateful control loop.

Final-answer-only testing is insufficient.

## 2. Unit testing

Test deterministic logic in isolation:

- state transitions,
- goal completion,
- action eligibility,
- decision scoring,
- action registry validation,
- repetition detection,
- retry budgets,
- termination,
- evidence support/contradiction/gap logic,
- belief updates,
- graph query validation,
- response-context construction,
- trace event validation/serialization.

## 3. Integration testing

Test real boundaries for representative cases:

```text
FastAPI ↔ orchestrator
PostgreSQL repositories
Neo4j queries
Qdrant retrieval
Redis adapters
LLM provider adapters
trace writer ↔ PostgreSQL
```

Use disposable/local service instances or controlled mocks as appropriate.

## 4. Orchestration tests

The LangGraph control loop must be tested as an actual cycle.

Required scenarios:

### Clear entity → graph

```text
text resolves entity
→ graph becomes eligible
→ graph query
→ evidence update
→ answer/continue
```

### Agent skipping

```text
active context unambiguous
+ follow-up state-resolvable
→ text/image agents are skipped
```

### Repeated agent invocation

```text
initial entity hypothesis
→ contradictory graph/image evidence
→ reassessment
→ Text/Entity Agent called again
```

### Multimodal contradiction

```text
Text → A
Image → B
→ contradiction
→ reassess
```

### Evidence gap

```text
graph returns partial evidence
→ gap detected
→ additional graph action
```

### Failure/retry

```text
transient failure
→ bounded retry
→ success or controlled recovery
```

### Loop guard

Repeated equivalent actions must terminate/redirect within configured limits.

### Clarification

```text
clarify
→ checkpoint
→ user reply
→ same lineage resumes
```

### Early termination

Sufficient evidence must prevent unnecessary extra actions.

## 5. Agentic behavior testing

Tests should compare selected actions with the **eligible action set and current state**, not blindly with one fixed sequence.

Example:

```text
Given:
- entity confidence sufficient for graph
- graph objective pending
- image absent

Then:
- GRAPH is eligible
- IMAGE is ineligible
- selected action must be eligible and consistent with the score/policy
```

When multiple actions are valid, the test should encode the valid set or state-dependent constraints.

## 6. API tests

Verify:

- request validation,
- response schemas,
- session lifecycle,
- discovery/conversation behavior,
- clarification/resume,
- streaming lifecycle,
- safe error responses,
- authorization once the auth mechanism is chosen,
- image validation.

Do not expose hidden chain-of-thought in streaming tests.

## 7. Database testing

Verify:

- migrations create required structures,
- repositories use parameterized queries,
- representative graph queries return expected relationships,
- evidence/provenance data round-trips correctly,
- state/trace records preserve identifiers and lineage.

## 8. Trace subsystem tests

### Event correctness

Verify required identifiers, event type, component/action, timestamps, status, evidence refs and lineage are present when applicable.

### Non-blocking behavior

Use a deliberately slow trace sink. The main orchestration operation must continue without waiting for persistence.

### Failure isolation

Force trace-writer/PostgreSQL failure and verify:

```text
main task result remains unaffected
trace failure is observable
```

### Bounded buffer

Fill the queue and verify that the process does not deadlock and the documented degradation policy is applied.

### Shutdown

Verify best-effort flush on clean shutdown.

### Snapshot reconstruction

Given persisted events/snapshots, the evaluator must reconstruct iteration-level state evolution for a representative run.

## 9. Security tests

Minimum tests:

- raw Cypher injection rejected,
- untrusted values parameterized,
- invalid/oversized images rejected,
- retrieved prompt-injection content cannot change action policy,
- Final LLM cannot use datastores/tools,
- unsupported evidence cannot be promoted,
- secrets do not appear in logs/traces,
- trace failure does not fail the task.

## 10. Golden traces

Golden traces should describe behavioral constraints rather than one exact path.

Valid examples can include:

```text
TEXT → IMAGE → GRAPH
IMAGE → TEXT → GRAPH
```

when both are independently useful and eligible.

Invalid example:

```text
GRAPH before sufficient entity resolution
```

Evaluate:

```text
state
→ eligible actions
→ selected action
→ rationale/score
→ observation
→ state change
→ terminal outcome
```

## 11. Benchmark data

Benchmark fixtures should cover:

- exact plant name,
- aliases/typos,
- ambiguity,
- image identification,
- text/image agreement,
- text/image conflict,
- graph evidence available,
- graph evidence absent,
- graph evidence gap,
- transient failures,
- clarification,
- safety/abstention cases.

Keep expected results stable. Do not alter benchmark labels to accommodate a failing implementation.

## 12. Test organization

```text
tests/
├── unit/
├── integration/
├── orchestration/
├── agentic/
├── api/
└── evaluation/
```

The exact framework/commands are not established until the repository scaffold is committed. Once selected, document exact commands in `DEVELOPMENT.md`.

## 13. Required evaluation metrics

### Quality

```text
Entity Top-1 Accuracy
Entity Top-k Accuracy
Image Top-1 Accuracy
Image Top-5 Accuracy
Graph Retrieval Precision
Graph Retrieval Recall
Evidence Correctness
Groundedness
Hallucination Rate
```

### Agentic

```text
Decision Correctness
Orchestrator Routing Accuracy
Replanning Rate
Belief Revision Success
Contradiction Recovery Success
Unnecessary Action Rate
Agent Invocation Efficiency
Average Iterations
Agent Calls per Turn
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
LLM Calls per Turn
Graph Queries per Turn
Token Consumption
Parallel Execution Benefit
```

Prefer trace-derived metrics.

## 14. Regression policy

Every discovered defect in control policy, graph safety, evidence/belief logic, trace lineage or critical session lifecycle receives a regression test before closure.

## 15. Acceptance

A change is acceptable only when the relevant tests pass, trace/evaluation behavior remains valid, safety boundaries remain enforced, and unresolved external-provider limitations are reported rather than hidden.
