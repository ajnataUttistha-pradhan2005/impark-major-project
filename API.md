# API.md — API Architecture and Contract

## 1. Role

FastAPI is the transport layer for:

- session creation/resume,
- discovery turns,
- conversation turns,
- optional image input,
- streaming progress/final responses,
- safe session status/errors,
- authorized trace/evaluation views.

Route handlers must call domain/orchestrator services and must not implement agent-selection logic.

## 2. Contract status

Phase-one implementation exposes `/health` and opt-in `/dev/conversations`, session retrieval,
`/{session_id}/state`, `/history`, `/turns`, `/clarifications`, `/images` and
`/dev/discovery/autocomplete`. See generated OpenAPI for provisional schemas. These are development
routes, not a frozen public API. `/state` exposes the safe summary only; raw domain state/trace reads
are not exposed. Streaming has typed contracts only; transport is still R-003.

The supplied architecture does not freeze exact public route paths, authentication, error-envelope schema, versioning or the primary streaming protocol.

Therefore:

> Exact public endpoint naming/authentication/streaming decisions are `TODO / DECISION REQUIRED` until committed.

Do not create a long-lived public API contract casually.

## 3. Logical API surface

| Capability | Logical operation | Requirement |
|---|---|---|
| Session | create | always starts in `discovery` |
| Session | get status | safe session summary |
| Turn | submit discovery input | text/image/text+image |
| Turn | submit conversation input | uses active context |
| Clarification | resume | same run/task lineage |
| Stream | subscribe | progress + final response |
| Trace | read | authorized research/evaluation use |
| Evaluation | read | authorized benchmark/metric use |
| Autocomplete | search | entity-resolution backed, read-only |

These are logical operations, not finalized URL paths.

## 4. Session API behavior

### Create

Conceptual request:

```json
{
  "mode": "discovery"
}
```

The server creates a session with discovery state.

### Retrieve

Safe response example:

```json
{
  "session_id": "session_123",
  "mode": "conversation",
  "active_plant": "Withania somnifera",
  "task_status": "ready"
}
```

Do not expose hidden chain-of-thought, raw prompts, private provider data or secrets.

## 5. Turn API

A turn may contain:

```text
session_id
text (optional)
image (optional)
client correlation/idempotency data if later selected
```

Validation:

- non-empty meaningful input unless the protocol intentionally supports an image-only turn,
- bounded text size,
- MIME/size validation for images,
- session existence and authorization,
- no raw Cypher field,
- no arbitrary action/tool field,
- correlation ID propagated to tracing where available.

The API forwards the turn to the orchestrator.

## 6. Discovery operations

A new session supports:

- plant name search,
- natural-language plant description,
- image upload,
- text + image,
- autocomplete.

Autocomplete should be backed by entity-resolution/search infrastructure and remain read-only until the user explicitly selects/establishes a candidate.

## 7. Conversation operations

Conversation mode supports:

- state-resolvable follow-ups without unnecessary agents,
- single-plant session lock and a new-chat notice for other plants,
- new image analysis when useful,
- graph retrieval when required and eligible,
- clarification/resume on the same task lineage.

## 8. Streaming

The backend must stream safe progress and final response data through the selected transport: SSE, WebSockets, or a documented combination.

Safe progress examples:

```text
discovery_started
candidate_found
agent_started
agent_completed
evidence_updated
clarification_required
answer_started
answer_completed
```

Do not stream hidden reasoning/chain-of-thought.

Streaming is not the durable trace system.

## 9. Clarification/resume

When task status becomes `WAITING_USER`:

- return a structured clarification payload,
- preserve session/run/task identifiers,
- resume the checkpointed state on the next user message,
- do not create a new unrelated session.

## 10. Error model

Logical error categories:

```text
VALIDATION_ERROR
UNAUTHORIZED
FORBIDDEN
NOT_FOUND
CONFLICT
RATE_LIMITED
DEPENDENCY_UNAVAILABLE
ORCHESTRATION_FAILED
EVIDENCE_UNAVAILABLE
WAITING_FOR_USER
SAFETY_ABSTENTION
INTERNAL_ERROR
```

Exact error JSON envelope is `TODO / DECISION REQUIRED`.

Never expose stack traces, secrets, raw Cypher, internal prompts or datastore credentials.

## 11. HTTP status policy

Once routes are frozen, use conventional categories:

```text
2xx → success
4xx → client/auth/policy errors
5xx → server/dependency errors not represented as domain terminal states
```

Exact status per endpoint is `TODO / DECISION REQUIRED`.

## 12. Authentication / authorization

Authentication mechanism: `TODO / DECISION REQUIRED`.

Required principles:

- authenticate at API boundary,
- centrally authorize access to session/trace/evaluation data,
- validate ownership/permissions rather than trusting client fields,
- protect research/evaluation routes more strongly than ordinary interaction routes.

## 13. CORS

CORS is configuration-driven. Do not use permanent wildcard access in deployment.

## 14. Pagination/filtering/sorting

Pagination is primarily relevant for trace/evaluation browsing and large autocomplete/search results.

Exact fields/limits are not established; add only what the UI/use case requires and make limits configurable.

## 15. Versioning

API versioning is `TODO / DECISION REQUIRED`.

Do not add compatibility layers that are unnecessary for the academic demonstration.

## 16. Trace API

A trace read surface should support safe retrieval of:

- run/session/turn identifiers,
- ordered events,
- state snapshot references,
- decisions/actions,
- observations/failures,
- evidence/provenance references,
- termination reason.

Do not expose secrets or hidden prompts/reasoning.

## 17. Evaluation API

A small read-only surface may expose:

- benchmark case status,
- metric summaries,
- run/trace-linked results,
- golden-trace comparisons.

Heavy evaluation remains offline in `backend/evaluation/`.

## 18. Idempotency and transport retries

Redis may support request deduplication. Exact idempotency-key behavior is `TODO / DECISION REQUIRED`.

Transport retry behavior must not be confused with orchestrator retry budgets. Agent/provider retries remain controlled by the harness.

## 19. API security invariants

The client cannot request:

```text
raw Cypher
arbitrary tool execution
arbitrary unregistered actions
Final LLM datastore access
```

All such concerns remain backend-owned.

## Implemented text discovery routes (2026-10-10)

The development routes under `/dev` now support PostgreSQL-backed sessions/history, text turns,
autocomplete and verified selection, same-lineage clarification, and `GET /dev/conversations/{id}/trace`.
`ChatResponse.understanding` exposes typed TextResult intent, candidates, stages, limitations and
clarification hints. `POST /turns` accepts `selected_plant_id`; `POST /clarifications` accepts the
returned clarification ID with text or an offered selected ID. See TEXT_ENTITY_GUIDE.md for commands.
These routes retain the development-only authorization gate; this is not a public production API.

## Interrupted-run recovery

POST `/dev/conversations/{session_id}/resume` continues a persisted RUNNING turn under its existing
run ID. Concurrent/new turns receive 409 until that run is recovered. Waiting-user responses use
the existing clarification endpoint. See HARNESS_GUIDE.md for at-least-once replay semantics.

### Single-plant session policy

All conversation responses include `session_notice`. After discovery establishes a plant, its
identity is locked. Another plant in text/image returns `SCOPE_REJECTED`; a conflicting explicit
selection returns HTTP 409 `PLANT_SCOPE_LOCKED`. Start a new session to discuss another plant.
Cross-plant comparisons/global reverse queries are out of scope. Graph evidence supports stable
citation IDs and `Trace evidence <UUID>` follow-ups within the recent same-session history.
See GRAPH_AGENT_GUIDE.md for the graph-result and provenance contracts.
