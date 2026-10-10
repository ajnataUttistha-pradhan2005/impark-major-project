# Text/entity discovery and search stores

The application uses the existing shared Neo4j driver, one async PostgreSQL pool, and one async
Qdrant client. PostgreSQL owns application state, turn history, evidence in state snapshots,
trace events, evaluations and the searchable name catalog. Qdrant holds name embeddings.
Neo4j remains the read-only source of medicinal-plant knowledge.

## Windows PowerShell setup

Run from the repository root with Docker Desktop's Linux engine running:

```powershell
Set-Location 'D:\MajorProject\Phase-2\impark-major-project'
.venv\Scripts\python.exe -m pip install -e '.[dev]'
.venv\Scripts\python.exe scripts/configure_local_search.py
docker start neo4j-dev
docker compose --profile stores up -d postgres qdrant
.venv\Scripts\python.exe -m backend.database.search_admin migrate
.venv\Scripts\python.exe -m backend.database.search_admin sync
.venv\Scripts\python.exe -m backend.database.search_admin health
```

The configuration script fills missing local settings and generates a database password in the
ignored `.env`. It does not print credentials or overwrite existing values. PostgreSQL uses
host port **15432**; Qdrant uses **6333**. Named Docker volumes preserve their data.
Keep the existing `neo4j-dev` container; do not start the separate Compose Neo4j service on its port.
Fill the four `NEO4J_*` connection fields in `.env` using your existing installation.
After migration/import, set:

```dotenv
APPLICATION_ENV=development
ENABLE_DEVELOPMENT_API=true
NEO4J_ENABLED=true
NEO4J_ALLOW_WRITES=false
TEXT_SEARCH_ENABLED=true
TEXT_SEMANTIC_ENABLED=true
```

```powershell
.venv\Scripts\python.exe -m backend
```

The Compose backend target remains a standalone foundation demo. The commands above run the
configured application on Windows against Docker stores. A containerized backend needs container-
reachable connection URLs in its environment (not `localhost` for sibling containers).

## Local/cloud switching

Only `.env` connection values change. Use `DATABASE_URL` with the provider's PostgreSQL hostname,
database, credentials and TLS options (typically `?sslmode=require`), `QDRANT_URL=https://...`
and `QDRANT_API_KEY`, plus Aura's secure `NEO4J_URI=neo4j+s://...` and credentials/database.
The same clients, repositories, migrations and Cypher are used. Do not put real credentials in
`.env.example`. Cloud connectivity has not been live-tested in this implementation.

Migration requires permission to create `pg_trgm` and tables. Run `migrate` and `sync` explicitly
against the intended deployment. Startup never creates schemas, seeds data or writes to Neo4j.
Changing embedding models requires matching dimensions and a separate collection/re-import;
incompatible collections fail validation instead of being recreated.

## Discovery API

These are development-only endpoints, disabled outside development. Production authentication and
ownership checks remain required before exposing them publicly.

```powershell
$base = 'http://127.0.0.1:8000'
Invoke-RestMethod "$base/health/postgres"
Invoke-RestMethod "$base/health/qdrant"
$session = Invoke-RestMethod "$base/dev/conversations" -Method Post
$id = $session.correlation.session_id
Invoke-RestMethod "$base/dev/discovery/autocomplete?q=nee"
$body = @{text='Which compounds are in neem leaves?'} | ConvertTo-Json
$answer = Invoke-RestMethod "$base/dev/conversations/$id/turns" -Method Post -ContentType 'application/json' -Body $body
$answer
Invoke-RestMethod "$base/dev/conversations/$id/trace"
```

Every session starts in `discovery`. Responses include `understanding`, candidates, match method,
alias metadata, confidence, active plant, citations and clarification when needed. Autocomplete
does not establish identity. Send its `plant_id` as `selected_plant_id` to `/turns` to select a
verified catalog plant. For `WAITING_USER`, POST the returned `clarification_id` and either `text`
or an offered `selected_plant_id` to `/clarifications`. This resumes the same run lineage.
After identity confirmation, mode becomes `conversation`. Follow-ups such as “its uses” and
“and sources?” reuse context; a different plant returns `SCOPE_REJECTED` and requires a new chat.

Supported retrieval includes plant details, parts, compounds, reported uses, protein targets,
bioactivities, evidence paths, citation tracing and source documents. Compound/use/target identifiers
are filtered to the active plant. Cross-plant comparisons and global reverse lookups are outside
the current single-plant session scope (superseding the previous comparison implementation).
Multiple plant-part scopes require clarification. Unrecognized requests, ambiguous aliases,
misspellings and semantic-only matches do not silently establish a high-confidence identity.
Multilingual aliases are supported; arbitrary multilingual question interpretation is not claimed.
Descriptions without a supported name may yield suggestions, but the source catalog has no
verified visual-description corpus and cannot establish identity from appearance alone.

## Import and retrieval

`sync` reads actual `PlantDetails` and `PlantAlias` properties, preserving alias type, language and
the original `normalized_alias`. Application normalization uses Unicode NFKC/casefold and retains
Indic combining marks. Stable application UUIDs are derived from source keys; no graph property
or relationship is invented. Additional compound, therapeutic-use and target identifiers/names
are projected for typed entity linking.

An explicit import creates a staging generation, batches embeddings, verifies the Qdrant point
count, then atomically activates the PostgreSQL generation. Retrieval filters vectors by that
generation. Failed staging cannot replace the active catalog; unchanged imports skip embedding.
Retired generations remain for recovery and require explicit future cleanup. Large source changes
during an import require a maintenance window; cross-store snapshot isolation is not provided.

Search uses exact IDs/names/aliases, PostgreSQL FTS, `pg_trgm`, RapidFuzz, then multilingual
MiniLM semantic retrieval. Fuzzy scores are capped below 0.95 and semantic scores below 0.80.
These are policy scores, not calibrated probabilities. A Qdrant timeout retains lexical results.
Graph retrieval remains allow-listed, parameterized, bounded and read-only. Unknown evidence
stays `unknown`; the final renderer receives only deterministic response context.

Decision-model fallback and its experimental artifacts have been removed. Unsupported or
ambiguous requests use clarification. The Text Agent interprets a request; the harness selects
the separate Knowledge Graph Agent for Neo4j retrieval.

## Validation and evaluation

```powershell
.venv\Scripts\python.exe -m pytest -q
$env:SEARCH_RUN_INTEGRATION='1'
$env:NEO4J_RUN_INTEGRATION='1'
$env:NEO4J_TEST_WRITES='1'
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check backend tests scripts
.venv\Scripts\python.exe -m mypy backend
.venv\Scripts\python.exe -m backend.evaluation.text_discovery --semantic
```

Integration tests require the imported local catalog and only permit local test databases for
write tests. They create/remove their own test records; they do not clear the knowledge graph.
The evaluator saves JSON under `data/evaluation/` and a PostgreSQL evaluation record.

Tracing uses a bounded non-blocking queue and background PostgreSQL writer. Writer failure/full
buffer cannot fail control execution. Dropped events mean a trace is incomplete; do not claim
complete benchmark reconstruction in that case. Sessions and interrupted domain state persist,
and LangGraph checkpoints now persist in PostgreSQL. Interrupted turns can be resumed explicitly
under the same run ID. Use one worker; see HARNESS_GUIDE.md for replay and image-input limits.

See [HARNESS_GUIDE.md](HARNESS_GUIDE.md) for checkpoint recovery, measured optimizations and teammate contracts.
