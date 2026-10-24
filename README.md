# IMPARK

For a detailed module-by-module explanation, teammate installation, and exact Docker
image/volume handoff instructions, use the [project and setup handbook](docs/README.md).
The verified cold-transfer files are currently in the ignored local folder
`backups/team-handoff/`; send that whole folder privately alongside the matching Git commit.
The handbook's receiver section explains checksum verification and restoration before Compose starts.

For a local Windows demo after configuring `.env`, the Python environment, frontend dependencies, and the existing `neo4j-dev` container, run `powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1` from the project root. The launcher starts PostgreSQL and Qdrant with Docker Compose, starts the backend and Next.js frontend when needed, checks their health, and warms plant-name search and the configured Ollama model. Open http://127.0.0.1:3000/. After code changes, pass `-Restart` to restart only verified IMPARK listeners and rebuild the production frontend. Use `-SkipDocker` when stores are already available elsewhere or `-DevFrontend` while developing. Startup logs are written under `data/demo-*.log`.

IMPARK is a single-user academic demonstration for Indian medicinal-plant discovery and
knowledge retrieval. A bounded, stateful LangGraph harness coordinates exactly three specialized
agents: Text/Entity, Image Understanding, and Knowledge Graph. Every chat begins in discovery,
establishes at most one active plant, then handles follow-up questions in conversation mode.
The harness chooses actions from current state, checks evidence and contradictions, and authorizes
the final response. The response model receives only a deterministic evidence context.

## Components

- FastAPI exposes versioned `/api/v1` chat, autocomplete, image-upload, run, evidence and replayable
  SSE endpoints. `/docs` exposes the API schema; [the frontend integration guide](frontend/README.md)
  explains the complete UI flow, and `frontend/contracts/` contains exported contracts.
- PostgreSQL stores chats, operations, messages, evidence snapshots, traces and text-search data.
  An explicitly imported MeSH definition cache can explain named use terms with its own citations.
  Redis is optional/transient. Neo4j holds the medicinal-plant knowledge graph; Qdrant holds
  separate text-name and image-reference vector collections.
- The Image Agent uses the supplied 40-class leaf Xception model plus Qdrant reference search.
  Image suggestions require user confirmation; plant-part and non-plant classification are not
  established. The graph agent uses typed, bounded, read-only queries.
- The response model is configured through `LLM_MODEL` (the current local demo uses
  `gemma4:e4b`). It turns server-approved evidence into readable answers. For an
  explanation follow-up, cited graph statements remain separate from clearly labeled
  general model background; rejected background falls back to grounded wording. Raw
  graph property maps are not sent as answers. The model cannot query databases,
  choose actions or create citations. Set
  `LLM_PROVIDER=grounded` to use deterministic rendering without Ollama.

## Local setup (Windows PowerShell)

Python 3.12+ and Docker are required. Copy `.env.example` to `.env` and configure local database
URLs, credentials and model settings there. Never commit `.env`. The source Neo4j graph and
supplied image artifacts are not bundled or automatically downloaded.

```powershell
Set-Location 'D:\MajorProject\Phase-2\impark-major-project'
py -3.12 -m venv .venv 
.\.venv\Scripts\python.exe -m pip install -e '.[dev,image]'
Copy-Item .env.example .env
docker compose --profile stores up -d postgres qdrant
# Start an existing populated Neo4j instance separately, or provision one for your graph.
.\.venv\Scripts\python.exe -m backend.database.search_admin migrate
.\.venv\Scripts\python.exe -m backend.database.search_admin sync
.\.venv\Scripts\python.exe -m backend.evidence.reference_import --limit 500
```

`sync` explicitly projects plant names and aliases from the configured Neo4j database into
PostgreSQL and Qdrant. It requires a populated graph and must be run against the intended stores.
The separate reference import reads only graph-linked MeSH descriptor IDs, verifies each ID and
label against the National Library of Medicine's descriptor and preferred-concept records, and
stores bounded definitions in PostgreSQL. It fetched 430 matching notes from the 446 distinct
IDs in the current local graph. The web server never fetches external pages to answer a turn;
missing notes simply leave the answer on graph evidence. A `Bioactivity.bioactivity_id` such as
`BA_001` is an internal graph ID, not a ChEMBL assay ID, so this importer does not claim to have
assay-specific ChEMBL descriptions. Add an authoritative assay identifier mapping before enabling
that kind of enrichment.
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
ollama pull gemma4:e4b
.\.venv\Scripts\python.exe -m backend.llm.admin warm
.\.venv\Scripts\python.exe -m backend
```

Open `http://127.0.0.1:8000/docs` or `http://127.0.0.1:8000/health`. Use one backend worker for
the MVP; durable operations and checkpoints rely on its single-process lease. New chats accept
text, an uploaded image ID, or both. The frontend must display the one-plant-per-chat notice and
use clarification IDs to resume pending discoveries.

In a second PowerShell terminal, start the Next.js frontend:

```powershell
Set-Location 'D:\MajorProject\Phase-2\impark-major-project\frontend'
npm install
Copy-Item .env.example .env.local
npm run dev
```

Open `http://127.0.0.1:3000`. The server-only `BACKEND_URL` points to FastAPI; set
`BACKEND_API_KEY` in `.env.local` only if the backend requires a key. See the
[frontend guide](frontend/README.md) for UI behavior and deployment configuration.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m mypy backend
Set-Location frontend
npm test
npm run typecheck
npm run build
```

Local integration tests are opt-in via `CHAT_RUN_INTEGRATION`, `GRAPH_RUN_INTEGRATION`,
`SEARCH_RUN_INTEGRATION`, `NEO4J_RUN_INTEGRATION`, `IMAGE_RUN_INTEGRATION`, and
`OLLAMA_RUN_INTEGRATION`. Stop the running backend first so tests can acquire the process lease.
Neo4j write tests have a separate opt-in and should not be enabled against the research graph.
The latest local non-integration sweep passed 387 tests (53 opt-in tests skipped); the separate
read-only live Neo4j/graph sweep passed 19 tests (two write-only tests skipped).
Four opt-in live Gemma explanation cases passed for compounds, plant parts, use terms and
assay measurements. A live Next.js-proxied chat established one plant, listed eight compounds,
explained all eight with the model, resolved citations, and deleted its temporary session.
These checks do not establish independent verification of pretrained knowledge, general image
accuracy, arbitrary-language coverage, multi-worker scalability or clinical safety.

This [teammate handbook](docs/README.md) and other README files are versioned. Other local
project notes remain excluded from Git, as is `langflow/`.
