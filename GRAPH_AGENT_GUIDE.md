# Graph Agent implementation and usage

The Graph Agent is now a typed, read-only retrieval capability integrated with the Text Agent
and deterministic LangGraph harness. It does not generate Cypher from language, choose actions,
mutate session state, or infer clinical efficacy.

## Current session scope

Every chat starts in discovery. Exactly one plant must be established before any graph query.
The harness then locks `Session.locked_plant_id` and switches to conversation. The original
information objective survives candidate clarification. A selected autocomplete plant plus a
question preserves both the selection's canonical name and the question.

Different-plant text/image results return `SCOPE_REJECTED`. A conflicting explicit selection
returns HTTP 409 `PLANT_SCOPE_LOCKED`. The active plant remains unchanged. Every chat API response
contains `session_notice`; the frontend must display it in discovery and conversation. The
frontend is currently a documented scaffold, so no implemented UI is claimed.

Cross-plant comparisons and global reverse lookups are outside this project scope. Historical
`COMPARE_PLANTS` remains in the contract for compatibility but cannot run. Reverse-query enum
names remain compatible; their repository implementations test membership ONLY within the
active plant. No request can use them to traverse other plants.

## Retrieval coverage

| Query | Retrieved scope |
|---|---|
| GET_PLANT_DETAILS | PlantDetails properties |
| GET_PLANT_PARTS / GET_PLANT_PART_DETAILS | HAS_PART; optional exact part ID or part name |
| GET_PHYTOCHEMICALS / GET_PHYTOCHEMICAL_DETAILS | HAS_PART → CONTAINS; optional InChIKey |
| GET_THERAPEUTIC_USES | HAS_PART → USED_FOR |
| GET_BIOACTIVITY | HAS_PART → CONTAINS → HAS_BIOACTIVITY |
| GET_PROTEIN_TARGETS | Above path → MEASURED_ON |
| GET_DOCUMENTS | Bioactivity path → REPORTED_IN |
| GET_EVIDENCE | Bioactivity path with optional document and target branches |
| GET_PLANTS_CONTAINING_COMPOUND | Active-plant membership for a compound |
| GET_PLANTS_FOR_THERAPEUTIC_USE | Active-plant membership for a use |
| GET_COMPOUNDS_TARGETING_PROTEIN | Active plant's compounds measured against a target |
| TRACE_EVIDENCE | Same-plant citation snapshot from bounded session history |
| COMPARE_PLANTS | Explicitly rejected by current project policy |

Plant alias search remains owned by Text/Entity and its Neo4j-backed name projection.
All graph patterns use verified labels, directed relationships and properties from the supplied
schema. No APOC, schema changes or database writes are required.

## Boundaries and evidence

- Application plant UUIDs resolve through the active PostgreSQL name generation to a canonical
  Neo4j plant name. Every database pattern anchors that plant.
- Static allow-listed Cypher uses parameters, a transaction timeout and an explicit result bound.
  `limit + 1` detects additional rows; at most `limit` (default 20, maximum 100) evidence paths
  are returned. Stable ordering and a truncation notice make this an explicitly bounded answer.
  Ask a narrower part/compound/target question to refine results; automatic pagination is not provided.
- Unsupported filters are reported, never silently dropped. All 17 verified plant-part values are mapped explicitly, including leaf/leaves, rhizome,
  aerial part, plant exudate and whole plant.
- Evidence contains actual node properties, relationship types, indexed edge endpoints (including
  branches), recorded URLs, graph scope and stable content-derived UUID citations. No string is
  silently truncated into invalid JSON. Oversized facts are omitted with an explicit limitation.
- `confidence=1` means an exact database projection, not medical certainty. Evidence class stays
  `unknown`: this graph has no verified clinical/evidence-class property. `source_quality=0`
  means ungraded, not a claim that a source is false. A high_confidence_tier is retained as data.
- Traditional uses have their own USED_FOR path; they are never joined to unrelated assay papers.
- Missing records are not negative proof. A deterministic empty result produces a terminal gap,
  avoiding repeated identical queries. Other pending objectives may still finish; partial evidence
  remains available with an EVIDENCE_UNAVAILABLE outcome and disclosed gaps.
- Conflicting properties observed for the same documented natural identifier produce data-quality
  contradictions with citation references. They do not weaken plant identity or invent a clinical
  contradiction. This bounded check is not an exhaustive graph consistency audit and does not
  compare incomparable assays or infer unsupported negative relationships.
- Transient/unavailable/timeout errors can retry within existing harness budgets. Authentication,
  configuration and permanent query errors do not retry. Provider errors are redacted.
- Recent citation history holds at most 100 evidence items and persists in the existing session
  JSON/checkpoint. `Trace evidence <citation UUID>` returns that snapshot and its actual source
  path; it explicitly says the snapshot is not a fresh database read. Unknown/expired/cross-plant
  citations produce a gap. New turns do not use old evidence to answer unrelated objectives.

## Integration

`backend/database/neo4j/repository.py` exposes `GraphRepository`; the shipped implementation is
`PlantGraphRetrieval` in `retrieval.py`. Inject it through the existing application wiring or
`AgentOverrides`. The harness binds and verifies plant scope before invocation, evaluates evidence,
retains citation history, and creates deterministic response_context for the response provider.
New result fields have backward-compatible defaults; no SQL migration is needed because existing
application state and checkpoints persist these contracts as JSON/typed state.

Graph tool start/completion/failure, latency, evidence count, gap count, contradictions and truncation
are emitted through the existing non-blocking trace recorder. Trace persistence never gates retrieval.

Example conversation:

1. `Which compounds are in neem leaves?` → establish neem, lock session, retrieve bounded paths.
2. `What are its uses?` → reuse neem, retrieve reported uses.
3. `Show evidence for neem` → retrieve assay/target/document associations with limitations.
4. `Trace evidence <returned citation UUID>` → explain the saved source path.
5. `Tell me about tulsi` → new-chat notice; neem remains active.

English intent patterns and multilingual aliases are supported. Arbitrary natural-language or
multilingual reasoning is not claimed. Ambiguous/unsupported requests ask for clarification.

## Windows validation

Use existing `.env` configuration for the local services. Do not paste credentials into commands.
These integration tests explicitly reject remote Neo4j/PostgreSQL hosts.

```powershell
.venv\Scripts\python.exe -m pytest -q
$env:GRAPH_RUN_INTEGRATION = '1'
$env:SEARCH_RUN_INTEGRATION = '1'
$env:NEO4J_RUN_INTEGRATION = '1'
.venv\Scripts\python.exe -m pytest -q --junitxml=data/evaluation/graph_agent_tests.xml
.venv\Scripts\ruff.exe check backend tests
.venv\Scripts\mypy.exe backend
.venv\Scripts\python.exe -m backend
```

Graph integration tests are read-only. Existing search integration tests perform isolated,
local application/checkpoint test writes. Set no Neo4j write-test flag for this validation.
Switching local/Aura still uses only existing NEO4J_* environment values; agent source is unchanged.
