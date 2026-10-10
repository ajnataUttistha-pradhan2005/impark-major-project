# Neo4j interface implementation — 2026-10-09

## Outcome

Implemented a reusable official-driver async connection/client and typed medicinal-plant read
repositories. Local Docker and Aura use identical code and queries; four `.env` connection values
select the target. The ignored local `.env` is configured for the user-provided local instance with
writes disabled. No credentials were added to tracked files.

No direct Neo4j connection implementations existed to migrate: the previous repository protocol
and Graph Agent were placeholders. Both remain compatible. The new shared client/repository are
available through the FastAPI lifecycle and dependency function. This focused change does not
implement the interrupted earlier PostgreSQL/full Text Agent task.

## Files changed

Modified:

- `.env.example`: blank connection placeholders, enablement/write guards and timeout/pool limits.
- `.gitignore`: documents existing environment-file exclusions.
- `pyproject.toml`: official Neo4j driver and explicit python-dotenv dependencies; integration marker.
- `requirements-dev.lock`: tested Neo4j 6.4.0 and its pytz dependency.
- `backend/config/settings.py`: inherits the single Neo4j configuration definition.
- `backend/main.py`: validates/opens once at startup, closes on shutdown, injects repository/client,
  adds `/health/neo4j`; leaves existing liveness and unrelated agent behavior intact.
- `DATABASE.md`, `DECISIONS.md`, `README.md`: records actual schema, design choices and guide link.

Created:

- `backend/database/neo4j/config.py`: validated configuration and side-effect-free dotenv loader.
- `backend/database/neo4j/driver.py`: driver/pool ownership, safe sessions and server handshake info.
- `backend/database/neo4j/client.py`: explicit read/write, transaction context/callback APIs,
  dictionaries/single/scalar, bounds and read-query classification.
- `backend/database/neo4j/errors.py`: redacted error categories and retryability.
- `backend/database/neo4j/models.py`: eight property models, using the source's real property types.
- `backend/database/neo4j/queries.py`: thirteen fixed parameterized templates.
- `backend/database/neo4j/medicinal.py`: bounded typed domain reads using exact graph directions.
- `backend/database/neo4j/diagnostics.py`: read-only schema/count/index/constraint inspection.
- `backend/database/neo4j/__main__.py`: health/inspect/plants CLI.
- `backend/api/dependencies/neo4j.py`: read repository injection for routes/services.
- `tests/neo4j/test_config.py`: required settings, URI families, environment precedence and bounds.
- `tests/neo4j/test_client.py`: lifecycle, parameters, reads/writes, rollback/cancellation, callbacks,
  cardinality, timeouts, result bounds, safe logs and URI-only switching.
- `tests/neo4j/test_repository.py`: fixed templates, input bounds and faithful property models.
- `tests/neo4j/test_lifespan.py`: configuration failures, readiness and one-driver lifecycle.
- `tests/neo4j/test_integration.py`: seven explicitly enabled local database tests.
- `NEO4J_GUIDE.md`: exact PowerShell setup/run/test commands, usage, configuration and limitations.
- `NEO4J_IMPLEMENTATION_REPORT.md`: this report.

Local-only file: `.env` (ignored; contains supplied connection credentials, never staged).

## Validation performed

All Python commands used the project `.venv/Scripts/python.exe`.

| Command | Result |
|---|---|
| `python -m pip install -e '.[dev]'` | Dependencies installed |
| `python -m pytest -q` with `NEO4J_RUN_INTEGRATION=1`, `NEO4J_TEST_WRITES=1` | **98 passed**, including seven live integration tests |
| `python -m ruff check backend tests scripts` | Passed |
| `python -m ruff format --check backend tests scripts` | Passed |
| `python -m mypy backend` | Passed, 80 source files |
| `python -m pip check` | No broken requirements |
| `python scripts/smoke_backend.py` | 79 modules imported, 52 shared schemas validated; real Uvicorn HTTP health passed after Neo4j startup; temporary server stopped |
| `python -m backend.database.neo4j inspect` | Verified server, exact label/relationship counts, indexes and constraints before/after transaction tests |
| `git diff --check` | Passed |
| `git check-ignore .env` | Confirmed ignored |

Local server: Neo4j Community **2026.09.0**; Bolt handshake **6.1**; driver **6.4.0**.
Before and after tests: **4,075 nodes**, **11,697 relationships**, **two LOOKUP indexes**,
**zero constraints**. All seven directed relationship counts matched the supplied inventory.

All thirteen domain templates executed against connected records selected from the actual graph,
including alias lookup, optional plant-part filtering, and compound/activity/target/document paths.
Atomic write tests create and delete a unique PlantDetails test record in the same transaction;
rollback tests never commit it. No graph clearing, seed, migration or persistent test data change.

During validation, tests exposed and fixed process-environment mutation during dotenv loading and
Python TimeoutError classification (it subclasses OSError). Regression tests remain in the suite.

## Limitations and decisions

- Aura was not contacted: no Aura connection details supplied. Secure URI configuration and
  unchanged driver factory/repositories are covered by unit tests; live Aura parity is not claimed.
- There is no automatic schema migration/seed operation, nor any dependency on APOC/Enterprise
  features. Missing indexes/constraints are not fabricated or copied between environments.
- Generic Cypher methods are for trusted backend code, not user/model text. Public consumers use
  the fixed repository; writes are separately enabled. READ routing alone is not authorization.
- EXPLAIN classification deliberately rejects non-read/system statements from read methods.
  The client does not claim to sandbox arbitrary third-party procedures or replace DB privileges.
- Node model fields permit absence rather than inferring constraints from inventory descriptions.
  Missing classyfire_class is preserved; evidence grades are not invented.
- Only this requested database interface was implemented in this turn. Existing Graph Agent,
  Final LLM and unrelated foundation capabilities retain their previous status.
- No commit or push was performed.

See [NEO4J_GUIDE.md](NEO4J_GUIDE.md) for commands and code examples.
