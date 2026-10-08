# SECURITY.md — Security Requirements

## 1. Security posture

This is an academic, health-adjacent demonstration rather than a medical production platform.

Primary security goals:

- prevent unsafe graph/tool execution,
- protect secrets,
- keep untrusted content as data,
- protect user/session data in logs and traces,
- preserve evidence integrity and uncertainty.

## 2. Authentication and authorization

Phase-one `/dev/*` routes are centrally denied unless APPLICATION_ENV=development and
ENABLE_DEVELOPMENT_API=true. This is a local integration bypass, not authentication. Bind to
loopback, use one worker, and do not deploy it as a public service. Image prototype limits and
discard-after-validation behavior are recorded under R-016 in DECISIONS.md.

Exact authentication architecture is not specified by the supplied design.

`TODO / DECISION REQUIRED`:

- authentication mechanism,
- user identity model,
- protected routes,
- roles/permissions.

Do not silently invent a JWT/OAuth architecture.

Once selected, authorization must be enforced centrally at API/domain boundaries. Trace/evaluation views should be more restricted than ordinary interaction endpoints.

## 3. Secrets

Never hard-code:

- DB credentials,
- Neo4j credentials,
- Qdrant credentials if used,
- model/API keys,
- signing/session secrets,
- sensitive private endpoints.

Use environment/configuration injection. `.env.example` contains names/placeholders only.

## 4. Input validation

Validate all external input:

- request data,
- session identifiers,
- filters/pagination,
- images and metadata,
- graph query objects,
- clarification payloads.

Reject invalid input before business logic.

## 5. Graph security

Hard boundary:

```text
user intent
→ typed graph query object
→ allow-list validation
→ parameter validation
→ parameterized Cypher
→ read-only Neo4j
```

Forbidden:

```text
user text → raw Cypher
LLM text → raw Cypher
string interpolation of untrusted graph values
```

Require bounded result counts and timeouts.

## 6. Prompt/data isolation

Treat as untrusted data:

- user content,
- graph text,
- retrieved documents,
- prior messages,
- text inside uploaded content.

Retrieved material must not override orchestration policy, security instructions or query allow-lists.

## 7. Final LLM boundary

The Final LLM cannot:

- access PostgreSQL,
- access Neo4j,
- access Qdrant,
- access Redis,
- call tools,
- choose actions,
- mutate state,
- invent citations/sources,
- upgrade evidence strength.

It receives only deterministic `response_context`.

## 8. Image security

Before inference:

- validate MIME type,
- enforce size limits,
- decode safely,
- reject corrupted/unsupported content,
- avoid trusting filename extension,
- bound image dimensions/work,
- apply documented upload lifecycle.

Exact limits are `TODO / Decision REQUIRED` if not set elsewhere.

## 9. API security

FastAPI must:

- validate requests,
- apply authentication/authorization once selected,
- return safe errors,
- avoid stack traces to clients,
- apply appropriate rate/abuse controls,
- use configuration-driven CORS.

CSRF handling depends on the final auth/transport decision.

## 10. CORS

Never treat `*` as a permanent deployment policy. Local development may use explicit local origins.

## 11. Logging and privacy

Do not place secrets, private prompts, raw images, full retrieved documents or unrestricted user content into normal logs.

Use IDs and references whenever possible.

Trace data is durable evaluation data and therefore also requires sanitization, access control and a retention policy.

`TODO / DECISION REQUIRED`:

- retention period,
- deletion policy,
- raw-content vs redacted/reference trace policy,
- trace-viewer authorization.

## 12. Evidence integrity

Store evidence class, provenance, confidence, support/contradiction and source references.

Do not turn "no evidence found" into "claim is false" unless the data model explicitly represents that distinction.

## 13. Health/safety behavior

The system is for academic/educational use.

For health-consequential questions:

- preserve evidence class,
- preserve uncertainty,
- avoid unsupported dosage/treatment claims,
- avoid implying diagnosis or clinical approval,
- use educational-use wording as required by the response policy.

## 14. Database security

### PostgreSQL

Use least-privilege credentials and parameterized queries.

### Neo4j

Use a read-only principal for the Knowledge Graph Agent.

### Redis

Do not expose Redis publicly.

### Qdrant

Restrict network exposure and credentials according to deployment.

## 15. Trace security

Trace persistence is subject to the same security expectations as application storage.

Required:

- sanitize payloads,
- never store secrets,
- bound event/snapshot size,
- avoid storing large raw image/document content unnecessarily,
- use correlation IDs rather than unnecessary direct identifiers.

Trace-writer failure must not cause task failure.

## 16. Dependencies

Add dependencies only when justified and compatible with the selected Python/frontend ecosystem. Avoid duplicate packages or unnecessary infrastructure.

## 17. Rate limiting

Redis may support rate limiting and request deduplication. Exact limits are configuration/decision items, not hard-coded assumptions.

## 18. Security tests

At minimum verify:

- graph injection rejection,
- parameterization,
- image validation,
- secret/log sanitization,
- retrieved-content isolation,
- Final LLM access boundary,
- evidence non-upgrading,
- trace failure isolation,
- final auth/authorization behavior.
