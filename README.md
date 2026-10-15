# IMPARK

IMPARK is a single-user academic demonstration for Indian medicinal-plant discovery and
knowledge retrieval. A bounded, stateful LangGraph harness coordinates exactly three specialized
agents: Text/Entity, Image Understanding, and Knowledge Graph. Every chat begins in discovery,
establishes at most one active plant, then handles follow-up questions in conversation mode.
The harness chooses actions from current state, checks evidence and contradictions, and authorizes
the final response. The response model receives only a deterministic evidence context.

## Components

- FastAPI exposes versioned `/api/v1` chat, autocomplete, image-upload, run, evidence and replayable
  SSE endpoints. `/docs` exposes the API schema; `frontend/contracts/` contains exported contracts.
- PostgreSQL stores chats, operations, messages, evidence snapshots, traces and text-search data.
  Redis is optional/transient. Neo4j holds the medicinal-plant knowledge graph; Qdrant holds
  separate text-name and image-reference vector collections.
- The Image Agent uses the supplied 40-class leaf Xception model plus Qdrant reference search.
  Image suggestions require user confirmation; plant-part and non-plant classification are not
  established. The graph agent uses typed, bounded, read-only queries.
- Ollama `qwen3:1.7b` is the local response-model option. Its output may order server-rendered
  evidence blocks; it cannot query databases, choose actions or create citations. Set
  `LLM_PROVIDER=grounded` to use deterministic rendering without Ollama.

## Local setup (Windows PowerShell)

Python 3.12+ and Docker are required. Copy `.env.example` to `.env` and configure local database
URLs, credentials and model settings there. Never commit `.env`. The source Neo4j graph and
supplied image artifacts are not bundled or automatically downloaded.

```powershell
Set-Location 'D:\MajorProject\Phase-2\impark-major-project'
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,image]'
Copy-Item .env.example .env
docker compose --profile stores up -d postgres qdrant
# Start an existing populated Neo4j instance separately, or provision one for your graph.
.\.venv\Scripts\python.exe -m backend.database.search_admin migrate
.\.venv\Scripts\python.exe -m backend.database.search_admin sync
```

`sync` explicitly projects plant names and aliases from the configured Neo4j database into
PostgreSQL and Qdrant. It requires a populated graph and must be run against the intended stores.
The web server does not migrate, seed or modify the graph at startup. For a first setup, configure
`POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` before starting Compose.

To enable image inference, place the supplied `xception_model.keras` and leaf-image `dataset/`
under `data/image/`. These large local assets are intentionally ignored by Git. The corrected
`data/image/class_indices.json` and index manifest are versioned. Build the image index explicitly:

```powershell
.\.venv\Scripts\python.exe -m backend.agents.image.admin extract --dataset data/image/dataset --model data/image/xception_model.keras --classes data/image/class_indices.json --output data/image/features.npz
.\.venv\Scripts\python.exe -m backend.agents.image.build_index --cache data/image/features.npz --manifest data/image/index_manifest.json
```

Set `IMAGE_ENABLED=true` and the `IMAGE_*_PATH` values in `.env` after indexing. For local response
generation, install/start Ollama and pull the configured model before launching the backend:

```powershell
ollama pull qwen3:1.7b
.\.venv\Scripts\python.exe -m backend.llm.admin warm
.\.venv\Scripts\python.exe -m backend
```

Open `http://127.0.0.1:8000/docs` or `http://127.0.0.1:8000/health`. Use one backend worker for
the MVP; durable operations and checkpoints rely on its single-process lease. New chats accept
text, an uploaded image ID, or both. The frontend must display the one-plant-per-chat notice and
use clarification IDs to resume pending discoveries.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m mypy backend
node --test frontend/api/client.test.mjs
```

Local integration tests are opt-in via `CHAT_RUN_INTEGRATION`, `GRAPH_RUN_INTEGRATION`,
`SEARCH_RUN_INTEGRATION`, `NEO4J_RUN_INTEGRATION`, `IMAGE_RUN_INTEGRATION`, and
`OLLAMA_RUN_INTEGRATION`. Stop the running backend first so tests can acquire the process lease.
Neo4j write tests have a separate opt-in and should not be enabled against the research graph.
The last safe local sweep passed 332 tests with two write-only tests skipped. This does not establish
general image accuracy, arbitrary-language coverage, multi-worker scalability or clinical safety.

The detailed project notes remain local and are intentionally excluded from Git. README files
remain versioned, except within the excluded `langflow/` directory.
