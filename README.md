# IMPARK

IMPARK is a single-workspace academic demonstration for identifying an Indian medicinal plant and exploring its recorded names, parts, compounds, uses, activities, targets, and sources. A chat begins in discovery and locks to one plant when confirmed. Its current execution path is a **DeepAgents main orchestrator with three specialist subagents**, wrapped by a LangGraph clarification/checkpoint graph. The former custom decision-loop harness is not the active runtime.

Start with the [documentation index](docs/README.md), then read the [implemented architecture](docs/architecture/README.md), [repository file map](docs/repository-map/README.md), [API and frontend contract](docs/api-and-frontend/README.md), and [setup and operations](docs/setup-and-operations/README.md). The [agent runtime guide](backend/orchestrator/deepagents/README.md) covers the current prompts and recovery path. These pages describe implementation, rather than a proposed design.

## Local demo

Use Python 3.12+, Node.js/npm, Docker Desktop, an existing populated Neo4j graph, and Ollama or another configured LangChain chat-model provider. Copy `.env.example` to `.env` and `frontend/.env.example` to `frontend/.env.local`; supply your own credentials and paths. Local image inference also requires the supplied model, class map, manifest, and dataset/index artifacts. The web server does **not** migrate databases or populate indexes at startup.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,image]'
Push-Location frontend
npm ci
Pop-Location
docker compose --profile stores up -d postgres qdrant
.\.venv\Scripts\python.exe -m backend.database.search_admin migrate
.\.venv\Scripts\python.exe -m backend.database.search_admin sync
powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1
```

Configure the exact local/container/cloud connection URLs in `.env` before running these commands. `sync` copies the configured Neo4j plant-name projection to PostgreSQL/Qdrant; it is an explicit administrative operation. The demo script can start the backend and Next.js frontend, check readiness, and warm configured services. Open <http://127.0.0.1:3000/> for the UI or <http://127.0.0.1:8000/docs> for the live OpenAPI explorer. See [setup and operations](docs/setup-and-operations/README.md) for restoration, optional image indexing, configuration, and troubleshooting.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m mypy backend
Push-Location frontend
npm test
npm run typecheck
npm run build
Pop-Location
```

Live integration tests are opt-in and require configured services and data; see [testing and limitations](docs/testing-and-limitations/README.md). This educational system does not establish clinical efficacy or independently verify every statement drawn from a model's pretrained knowledge.
