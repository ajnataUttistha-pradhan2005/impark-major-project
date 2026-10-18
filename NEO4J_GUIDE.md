# Shared Neo4j interface

The same Python modules and Cypher templates connect to local Docker or Aura. Change connection
values in `.env` and restart the process. There are no environment-specific repository branches,
TLS overrides, APOC dependencies, startup migrations, seeds or database-clear operations.

## Architecture

| File | Responsibility |
|---|---|
| `backend/database/neo4j/config.py` | Required connection values, URI validation and bounds; dotenv/environment loading |
| `backend/database/neo4j/driver.py` | One async official driver/pool per application lifespan; sessions and shutdown |
| `backend/database/neo4j/client.py` | Trusted backend read/write, transaction context/callbacks, dictionaries/single/scalar |
| `backend/database/neo4j/errors.py` | Safe error codes without raw Cypher, parameter values or driver messages |
| `backend/database/neo4j/models.py` | All eight node property models from the supplied inventory |
| `backend/database/neo4j/queries.py` | Thirteen fixed parameterized read templates |
| `backend/database/neo4j/medicinal.py` | Bounded typed domain repository |
| `backend/database/neo4j/diagnostics.py`, `__main__.py` | Explicit read-only CLI health, schema inspection and example reads |
| `backend/api/dependencies/neo4j.py` | Read repository dependency for application routes/services |
| `tests/neo4j/` | Unit, lifecycle and explicitly enabled local integration tests |

The existing `GraphRepository` protocol and Graph Agent placeholder remain unchanged. There were
no direct Neo4j connections or working medicinal Cypher implementations in the starting code.
New callers use this shared layer rather than creating drivers. The Graph Agent still requires a
separate evidence/Observation adapter before providing end-user graph answers; this task does not
invent evidence classes or implement unrelated Text/Entity/PostgreSQL functionality.

The general client accepts trusted application-owned Cypher; never pass user/model query strings
to it or expose it as an HTTP execution endpoint. Application consumers should normally use
`MedicinalPlantRepository`. Writes are separately gated by `NEO4J_ALLOW_WRITES` (false by default).
Read APIs use READ routing and EXPLAIN classification; non-read statements are rejected before
execution. This is a guard, not a substitute for the server's privileges. Some administrative
procedures are classified as system operations and rejected; server version diagnostics use the
driver handshake instead. There is no Cypher keyword blacklist.

## Windows PowerShell setup

From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
# Only if .env does not already exist:
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
docker ps --filter name=neo4j-dev
# Only if your existing container is stopped:
docker start neo4j-dev
```

Your existing `neo4j-dev` container is sufficient. Do not start the optional Compose Neo4j service
on the same ports. No container/schema recreation is required.

For local Docker, set these values in `.env` (enter your own password):

```dotenv
APPLICATION_ENV=development
NEO4J_ENABLED=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<LOCAL_PASSWORD>
NEO4J_DATABASE=neo4j
NEO4J_ALLOW_WRITES=false
```

Run:

```powershell
.\.venv\Scripts\python.exe -m backend.database.neo4j health
.\.venv\Scripts\python.exe -m backend.database.neo4j inspect
.\.venv\Scripts\python.exe -m backend.database.neo4j plants
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
# In another terminal:
Invoke-RestMethod http://127.0.0.1:8000/health/neo4j
```

`/health` remains application liveness; `/health/neo4j` returns 200 for a successful database probe,
503 when disabled/unavailable. No credentials or database internals appear in this endpoint.
When `NEO4J_ENABLED=true`, missing/invalid settings or a failed startup connection fail startup
clearly. Explicitly disabling Neo4j retains the standalone foundation/test mode.

## Switch to Aura using only .env

Replace the **four connection values**, keeping the same code and commands:

```dotenv
NEO4J_URI=neo4j+s://<YOUR_AURA_HOST>
NEO4J_USERNAME=<YOUR_AURA_USERNAME>
NEO4J_PASSWORD=<YOUR_AURA_PASSWORD>
NEO4J_DATABASE=<YOUR_AURA_DATABASE>
```

Use the exact secure URI/database supplied by Aura. URI scheme controls encryption/routing; no
source-code change is needed. Restart Uvicorn after editing. Clear stale PowerShell environment
overrides if present: process environment intentionally takes precedence over `.env`.
Use `APPLICATION_ENV=production` when deploying the application; its unrelated development API
remains disabled in production until authentication is implemented. No local data is copied to Aura.
Aura connectivity was not tested because no Aura connection details were provided.

`.env` and `.env.*` remain Git-ignored (except the placeholder `.env.example`). The local config
created for this task is ignored; credentials are not in source, examples, reports or tests.
Both CLI loading (`dotenv_values`) and Pydantic Settings use python-dotenv without changing the
global process environment.

## Configuration and limits

| Environment variable | Default |
|---|---:|
| `NEO4J_ENABLED` | false |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | No defaults; all required when enabled |
| `NEO4J_ALLOW_WRITES` | false |
| `NEO4J_TRANSACTION_TIMEOUT_SECONDS` | 10 |
| `NEO4J_CONNECTION_TIMEOUT_SECONDS` | 5 |
| `NEO4J_ACQUISITION_TIMEOUT_SECONDS` | 10 |
| `NEO4J_MAX_POOL_SIZE` | 20 |
| `NEO4J_MAX_RESULT_RECORDS` | 1000 |

Each domain query additionally limits results to at most 100 and uses a bounded timeout. An
operation may lower its timeout but cannot exceed the configured transaction bound. Results are
consumed within the transaction; excess records cause rollback and a RESULT_LIMIT error, not silent
truncation. There is no hidden driver retry loop: the orchestrator owns retries. Standalone callers
may retry only when appropriate to their transaction/idempotency requirements.

## Python usage

```python
from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import load_neo4j_config
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.neo4j.medicinal import MedicinalPlantRepository

async def example() -> None:
    async with Neo4jConnection(load_neo4j_config()) as connection:
        client = Neo4jClient(connection)
        repository = MedicinalPlantRepository(client)
        plants = await repository.list_plants(limit=5)
        if plants and plants[0].plant_name:
            parts = await repository.parts(plants[0].plant_name)
        row = await client.single("RETURN $value AS value", {"value": "parameter data"})
        count = await client.scalar("MATCH (n:PlantDetails) RETURN count(n)")

        # Multiple operations in ONE transaction; automatic rollback on error/cancellation.
        async with client.transaction() as tx:
            first = await tx.records("RETURN $value AS value", {"value": 1})
            second = await tx.scalar("RETURN $value AS value", {"value": 2})
```

Inside FastAPI, reuse `app.state.plant_repository` or `get_plant_repository` via `Depends`; do not
open another driver per request. `app.state.neo4j` is the trusted application client.

Maintenance code can use `client.write(...)`, `client.transaction(write=True)`, or
`client.execute_write(async_callback)` only with writes explicitly enabled. `execute_read` and
`execute_write` callbacks share a single transaction and are not automatically replayed. Do not
perform external side effects inside transactions. `single` rejects multiple rows; `scalar` also
requires exactly one column (both return None for no records). Transaction objects must not escape
their context and cannot be shared concurrently.

Do not create indexes/constraints just because the local graph lacks them. Schema changes require
an explicit reviewed migration/maintenance command. None are supplied or run by this change.

## Source fidelity and live verification

Source: `D:\docs\Major Project\neo4j_database_design.md` supplied on 2026-10-09. It supersedes
the earlier Plant_details/Plant_part/Therapeutic_Uses metadata. The implemented names are
`PlantDetails`, `PlantAlias`, `PlantPart`, `Phytochemicals`, `TherapeuticUse`, `Bioactivity`,
`Protein_Target`, `Document`. Only the seven documented directed relationships are traversed.

The local server reported Neo4j Community **2026.09.0**, 4,075 nodes, 11,697 relationships,
two default LOOKUP indexes and no constraints. These are observations, never runtime constants.
The server advertises Cypher 5 and 25; queries use established syntax without Enterprise/APOC
features. Driver version tested: **6.4.0**.

No uniqueness or cardinality is assumed. Exact lookups return lists. Node fields are nullable
projections because inventory NOT NULL text is not a verified constraint. In particular,
`Phytochemicals.classyfire_class` can be absent. `standard_value`/`normalized_value_nm` retain float
types, `Document.source_id` retains integer type, and years remain strings. No evidence-class
property or direct PlantDetails-to-Document relationship was invented.

## Tests

```powershell
# All ordinary tests; live integration tests explicitly skip unless enabled:
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests scripts
.\.venv\Scripts\python.exe -m ruff format --check backend tests scripts
.\.venv\Scripts\python.exe -m mypy backend

# Local integration reads; a loopback URI and development environment are required:
$env:NEO4J_RUN_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest tests/neo4j/test_integration.py -q

# Also enable atomic-write/rollback tests, then clear both explicit test flags:
$env:NEO4J_TEST_WRITES = '1'
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:NEO4J_RUN_INTEGRATION
Remove-Item Env:NEO4J_TEST_WRITES
```

Tests refuse remote/Aura targets. Write tests use unique PlantDetails names and delete within the
same transaction or intentionally roll back; no test node is permanently committed. They never
clear or seed the graph. Use `NEO4J_TEST_ENV_FILE` to select another local test environment file.
The integration tests select representative connected records from the live graph rather than
invent sample IDs or assume the export's counts are permanent.

Driver API references: [async API](https://neo4j.com/docs/api/python-driver/current/async_api.html)
and [transaction guidance](https://neo4j.com/docs/python-manual/current/transactions/).
