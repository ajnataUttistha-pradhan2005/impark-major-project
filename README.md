# IMPARK

IMPARK is a single-workspace academic demonstration for identifying an Indian medicinal plant and exploring its recorded names, parts, compounds, uses, activities, targets, and sources. A chat begins in discovery and locks to one plant when confirmed. Its current execution path is a **DeepAgents main orchestrator with three specialist subagents**, wrapped by a LangGraph clarification/checkpoint graph. The former custom decision-loop harness is not the active runtime.

Start with the [documentation index](docs/README.md), then read the [implemented architecture](docs/architecture/README.md), [repository file map](docs/repository-map/README.md), [API and frontend contract](docs/api-and-frontend/README.md), and [setup and operations](docs/setup-and-operations/README.md). The [agent runtime guide](backend/orchestrator/deepagents/README.md) covers the current prompts and recovery path. These pages describe implementation, rather than a proposed design.

## Local demo

Use Python 3.12+, Node.js/npm, Docker Desktop, an existing populated Neo4j graph, and Ollama or another configured LangChain chat-model provider. Copy `.env.example` to `.env` and `frontend/.env.example` to `frontend/.env.local`; supply the **credentials from the exported database volumes** when restoring a teammate handoff. Local image inference also requires the supplied model, class map, manifest, and dataset/index artifacts. The web server does **not** migrate databases or populate indexes at startup. For a new teammate machine, follow the [step-by-step handoff guide](docs/setup-and-operations/README.md) before running the launcher.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,image]'
Push-Location frontend
npm ci
Pop-Location
# For a supplied cold handoff, restore its verified volumes and image assets first:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restore_team_handoff.ps1
ollama pull gemma4:e4b
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo.ps1
```

Configure the exact local/container/cloud connection URLs in `.env` **before** restoring or launching. The command above assumes the six handoff files are in `backups/team-handoff/` and the target volumes do not already exist. A fresh build **without** the handoff instead requires a populated Neo4j graph followed by explicit `search_admin migrate` and `sync`; do not rerun `sync` on an intact restored projection. The demo script checks configuration, starts/checks services, and warms the active main model. Open <http://127.0.0.1:3000/> for the UI or <http://127.0.0.1:8000/docs> for the live OpenAPI explorer. See [setup and operations](docs/setup-and-operations/README.md) for both paths, safe reset, and troubleshooting.

## Observability & Evaluation

IMPARK includes a self-hosted, decoupled multi-agent evaluation architecture powered by **Arize Phoenix**, **Redis Streams**, and a local **Gemma 4 (`gemma4:e4b`)** instance serving as an LLM judge:
* **Trace Routing & Queue**: Non-blocking (< 1ms) OpenTelemetry span push to Redis Streams (`phoenix-agent-traces`).
* **Sequential LLM Judge**: Evaluates `graph_retrieval_time`, `tool_selection_accuracy`, `groundedness`, and `hallucination_rate` with zero parallel thread VRAM collisions.
* **Persistent Storage & UI**: Stores traces and evaluations permanently in PostgreSQL 16 (`phoenix` db), with real-time visualization in the Arize Phoenix UI (<http://localhost:6006>).

To launch the evaluation pipeline locally or on AWS EC2, follow the [Evaluator Guide](evaluator/README.md):

```powershell
# 1. Start Evaluator Infrastructure (Redis, Postgres, Arize Phoenix)
cd evaluator
docker compose up -d

# 2. Run the Arize Phoenix + Gemma 4 Evaluation Pipeline
python phoenix_pipeline.py

# 3. Or run the continuous idle-aware background worker daemon
python phoenix_pipeline.py --worker

# 4. Run automated test suite
pytest test_phoenix_pipeline.py -v
```

For 1-command automated deployments:
* **Windows**: `.\evaluator\deploy_windows.ps1`
* **AWS EC2 (Linux)**: `./evaluator/deploy_ec2.sh`
* **AWS EC2 (Linux)**: `./evaluator/deploy_ec2.sh`

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
