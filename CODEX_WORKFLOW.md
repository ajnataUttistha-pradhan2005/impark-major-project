# CODEX_WORKFLOW.md — Codex Operating Procedure

## 1. Purpose

Codex should implement this project carefully from the repository source of truth. It must inspect existing code before modifying it and must not silently invent major architecture decisions.

## 2. Mandatory startup sequence

```text
1. Read AGENTS.md.
2. Read relevant sections of INSTRUCTIONS.md.
3. Read ARCHITECTURE.md and PROJECT_STRUCTURE.md.
4. Read the relevant coding/testing/security/API/database document.
5. Read DECISIONS.md.
6. Inspect the actual repository tree.
7. Inspect package manifests, migrations, existing tests and configuration.
8. Identify the smallest task from TASKS.md that satisfies the requested change.
```

## 3. Implementation sequence

```text
understand requirement
→ inspect implementation
→ identify dependencies
→ make smallest coherent change
→ add/update tests
→ add trace coverage
→ run focused validation
→ run broader validation
→ review diff
→ update docs/decisions
→ report result
```

## 4. Architecture invariants Codex must protect

Never:

- add a fourth specialized agent,
- put action-selection authority inside a specialized agent,
- give the Final LLM datastore/tool access,
- accept raw Cypher from user/model text,
- make trace persistence synchronously block orchestration,
- create an unrestricted planner agent that replaces deterministic policy,
- turn the system into a fixed pipeline disguised as a branch tree,
- start a new session for clarification,
- rerun all agents on every follow-up regardless of state.

## 5. Ambiguity handling

### Local/reversible ambiguity

Choose a simple reversible implementation when it does not change architecture. Mention it in the completion report.

### Architectural ambiguity

Do not silently decide. Examples:

- authentication,
- exact public API,
- primary streaming transport,
- frontend framework/package manager,
- database schema/migration tool,
- model selection,
- trace retention/degradation policy.

Update `DECISIONS.md` with `TODO / DECISION REQUIRED` until resolved.

## 6. Conflict handling

When requirements conflict:

1. identify the conflict,
2. use the source-of-truth hierarchy from `AGENTS.md`,
3. prefer explicit final requirements over rough pseudocode,
4. preserve working code when not contradicted,
5. document unresolved conflict/decision.

The supplied HLD contains rough/not-final pseudocode. Treat it as illustrative where it conflicts with the established architectural invariants.

## 7. Existing-code changes

Before changing a public contract:

- inspect all callers,
- inspect tests,
- inspect DB migrations/config,
- determine whether compatibility matters.

Avoid unrelated refactors and formatting churn.

## 8. Testing rules

For each feature:

- deterministic logic → unit tests,
- control-loop change → orchestration/agentic tests,
- DB/provider boundary → integration tests,
- API change → API tests,
- behavior change → regression test.

Do not encode a single exact action sequence when multiple state-justified sequences are valid.

## 9. Trace rules

Every meaningful control path must produce trace evidence sufficient to reconstruct:

```text
state
→ eligible actions
→ decision
→ action/invocation
→ observation/failure
→ evidence/belief update
→ termination/replan
```

Trace recording must be non-blocking. If persistence fails, the main task continues.

## 10. Failure handling

When something fails:

```text
inspect
→ classify code/environment/dependency issue
→ fix if in scope
→ add regression test when useful
→ rerun focused checks
→ rerun affected broader checks
```

Never hide a failure by weakening an assertion or silently skipping a relevant test.

## 11. New dependencies

Before adding a package:

1. inspect existing dependencies,
2. confirm the capability is not already available,
3. verify it fits the one-month scope,
4. add it through the repository package manager,
5. update docs/config/tests,
6. add a decision record if architecture changes.

## 12. Database changes

Use migration-backed changes:

```text
update schema/model/repository
→ migration
→ integration tests
→ seed compatibility check
→ DATABASE.md update
```

Do not rely on implicit startup schema mutation.

## 13. API changes

Keep routes thin:

```text
request validation
→ domain command
→ orchestrator/service
→ response
```

Do not implement routing policy in FastAPI route code.

## 14. Frontend changes

The frontend is a client, not a second orchestrator.

Respect:

```text
discovery before conversation
active context
candidate selection
stateful follow-up
safe progress streaming
trace/evaluation separation
```

Never render hidden chain-of-thought.

## 15. Scope control

Defer these unless a later explicit requirement changes scope:

```text
Kubernetes
Kafka/NATS
service mesh
multi-region deployment
enterprise identity federation
production autoscaling
distributed GPU scheduling
```

## 16. Completion report

Every implementation task should end with:

```text
Implemented:
- files/behavior changed

Validated:
- commands/tests actually run

Trace/Evaluation:
- event/metric coverage added

Decisions:
- decisions made or TODOs created

Remaining:
- unresolved issues/limitations
```

Never claim a command was run if it was not run.

## 17. Recommended prompt granularity

Ask Codex to implement one logical task/milestone at a time.

Example:

```text
Implement F2-01 from TASKS.md. Inspect the existing repository first. Add the typed bounded Action Registry and unit tests. Do not implement F2-02/F2-03 yet. Preserve the architecture and add trace metadata where appropriate.
```

Then move to:

```text
Implement F3-01 through F3-03. Build the non-blocking trace recorder/buffer and background writer. Prove trace-writer failures do not fail the main task with tests.
```

## 18. Final operating rule

Prefer a small, typed, deterministic, testable, traceable implementation that makes the architecture visible in code and evaluation traces. Do not replace bounded engineering with clever but opaque autonomy.
