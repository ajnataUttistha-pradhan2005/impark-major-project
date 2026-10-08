# CODING_STANDARDS.md — Project-Specific Coding Standards

## 1. Priority

Optimize for:

1. correctness,
2. traceability,
3. explicit architecture boundaries,
4. testability,
5. minimal complexity appropriate to a one-month academic project.

Do not optimize for production-scale infrastructure.

## 2. Python

- Target Python 3.12+.
- Type new public functions, domain models and provider interfaces.
- Use Pydantic v2 for external/API contracts.
- Use typed state models/`TypedDict` where appropriate for LangGraph state.
- Prefer `async def` for I/O-bound operations.
- Do not block the event loop with heavy CPU/GPU work.
- Avoid untyped dictionaries for important domain structures.
- Keep modules small and cohesive.

## 3. Naming

Python:

```text
modules/functions/variables  → snake_case
classes                       → PascalCase
constants                     → UPPER_SNAKE_CASE
```

Boolean values should read as predicates, e.g. `is_resolved`, `has_image`, `requires_clarification`.

Use explicit correlation IDs:

```text
run_id
session_id
turn_id
iteration
decision_id
action_id
agent_invocation_id
observation_id
evidence_id
source_id
```

Action identifiers are stable uppercase values, e.g. `RETRIEVE_GRAPH`. Domain trace event identifiers should be stable and version-controlled.

## 4. State modeling

Keep concerns logically separated:

```text
goal
belief/hypotheses
evidence/provenance
execution/history
decision
control/termination
conversation context
```

Agents return observations/failures. The orchestrator owns state mutation.

Do not make an agent mutate global `ConversationState` as a hidden side effect.

## 5. Deterministic vs model-driven logic

Deterministic code owns:

- action eligibility,
- graph safety,
- retry/iteration budgets,
- loop detection,
- evidence typing,
- termination,
- response-context construction.

LLMs may assist:

- text/entity interpretation,
- bounded entity disambiguation inside Text/Entity Agent,
- optional decision suggestion/tie-break,
- final natural-language generation.

Never move a hard safety/control invariant into an LLM prompt.

## 6. Function design

Prefer small functions with explicit inputs/outputs.

Examples:

```python
def enumerate_eligible_actions(state: ConversationState) -> list[Action]: ...

def score_action(action: Action, state: ConversationState) -> float: ...

def evaluate_observation(state: ConversationState, observation: Observation) -> EvidenceUpdate: ...
```

Do not create one giant orchestration function containing routing, database operations, model calls and response generation.

## 7. Error handling

Distinguish:

```text
validation failure
transient dependency failure
permanent capability failure
policy/safety rejection
evidence insufficiency
trace persistence failure
```

Trace persistence failure is not a business-task failure.

Avoid bare `except Exception: pass`. At top-level boundaries, catch broadly only to convert an unexpected failure into a safe structured failure and/or a controlled terminal state.

## 8. Retry behavior

Retry only through the configured recovery policy.

Never write unbounded retry loops.

Every retry must be traceable with its action/attempt correlation.

## 9. Logging

Use structured logging through the chosen logging stack.

Recommended fields:

```text
timestamp
level
service
run_id
session_id
turn_id
iteration
component
event
action
status
latency_ms
trace_id
```

Levels:

- `DEBUG`: detailed development diagnostics.
- `INFO`: lifecycle events useful in normal operation.
- `WARNING`: recoverable abnormal condition.
- `ERROR`: failed operation requiring attention.
- `CRITICAL`: process/integrity failure.

Never log secrets. Do not automatically log full user content, raw images, full retrieved documents or private model prompts.

## 10. Trace events

A trace event is a structured evaluation record, not merely a log line.

Every meaningful control path should make these questions answerable:

```text
What decision was made?
What action was selected?
What observation/failure occurred?
What evidence changed?
What belief/state changed?
Why did execution continue/stop?
```

Trace recording must be non-blocking to the task caller.

## 11. Evidence handling

Always retain evidence class and provenance.

Never upgrade:

```text
traditional → clinical
preclinical → established
```

through wording alone.

Keep modality-specific evidence so later evaluation can determine whether the image, text or graph changed the belief.

## 12. Agent contracts

Every specialized agent uses a typed contract returning:

```text
Observation | Failure
```

Provider-specific raw output stays behind the agent/provider adapter.

The agent should not decide the next orchestrator action.

## 13. Dependency inversion

Use replaceable interfaces/protocols for:

- `LLMProvider`,
- image inference provider,
- graph provider,
- vector provider,
- trace sink/writer,
- persistence repositories.

Changing from Ollama to vLLM or changing an image model must not require rewriting orchestration policy.

## 14. API code

- Thin route handlers.
- Validate at the API boundary.
- Convert transport models to domain commands.
- Use typed responses.
- Centralize authorization.
- Propagate correlation identifiers into runtime/tracing.
- Never expose stack traces or secrets.

Do not choose agents directly from route handlers.

## 15. Database code

- Keep SQL/Cypher in repository/adapter modules.
- Parameterize all queries.
- Keep transactions explicit where consistency matters.
- Add indexes for real lookup patterns.
- Use stable IDs rather than display names as relationship keys where stable IDs exist.
- Keep graph operations read-only and bounded.
- Apply schema changes only through migrations.

## 16. Cypher security

Required path:

```text
typed query object
→ allow-list validator
→ validated parameters
→ parameterized Cypher
→ Neo4j
```

Forbidden:

```text
f"...{user_input}..." → Cypher
LLM-generated arbitrary Cypher → Neo4j
```

## 17. Async/concurrency

Use concurrency only when actions are independent and policy permits it.

For parallel action sets:

- share a decision parent ID,
- correlate each branch,
- collect observations before joint evaluation,
- handle partial failure explicitly,
- trace start/completion/cancellation.

Do not run all agents on every request.

## 18. Configuration

Externalize configuration for:

```text
database URLs/credentials
Redis URL
Neo4j URL/credentials
Qdrant URL
LLM provider/model
confidence thresholds
iteration/retry limits
trace buffer size/degradation policy
CORS origins
```

Use environment/config models. Never commit real values.

## 19. Frontend conventions

The frontend is a client of backend domain behavior.

Discovery and conversation should be clearly distinct. Progress should show safe operational events rather than hidden chain-of-thought. Evidence/uncertainty must be represented faithfully.

Do not create a second orchestration engine in the frontend.

## 20. Comments and documentation

Comments explain non-obvious invariants, safety boundaries, or temporary workarounds. Do not comment obvious code.

Document public domain interfaces and architecture-changing behavior.

## 21. Performance

- Reuse state when it already resolves a follow-up.
- Avoid unnecessary agent calls.
- Bound graph/vector/model work.
- Prefer concurrent independent I/O where useful.
- Keep trace work off the control path.
- Do not sacrifice trace/evidence required for evaluation just to improve latency.

## 22. Existing code changes

Before modifying an existing module:

1. inspect tests and call sites;
2. understand current contracts;
3. preserve behavior outside requested scope;
4. make a minimal change;
5. add regression tests;
6. review the diff.

Avoid unrelated refactors and formatting churn.
