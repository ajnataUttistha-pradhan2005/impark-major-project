# IMPARK project and teammate setup handbook

This handbook describes the code **as it currently exists** and a repeatable Windows development handoff. IMPARK is a single-user academic demo for discovering an Indian medicinal plant and asking grounded questions about that plant. It is not a diagnosis or treatment system. Read the root [README](../README.md) for the short launch path and the [frontend integration guide](../frontend/README.md) for every HTTP/SSE contract.

## 1. What runs, and where the data lives

```text
Next.js browser UI → same-origin /api/v1 proxy → FastAPI RunManager
                                              → LangGraph + custom Harness
                                                    ├─ Text / Entity Agent
                                                    ├─ Image Understanding Agent
                                                    └─ Knowledge Graph Agent
                                              → deterministic response_context
                                              → guarded Ollama Final LLM / grounded fallback
                                              → replayable SSE + persisted messages
```

Every new chat starts in discovery. The text agent resolves a name/alias or description; the image agent can propose a leaf-image identification. The harness assesses the observations, may ask for clarification, and locks **one active plant** only after a valid identification. Conversation questions and elliptical follow-ups reuse that plant; a different plant requires a new chat. The harness selects from a finite action registry based on current state, budgets, evidence and contradictions. The Final LLM writes only from its deterministic response packet and cannot call a database or select an action.

| Service | Local development role | Persistent data |
| --- | --- | --- |
| FastAPI/Python | `/api/v1`, operations, agents, harness, response generation | PostgreSQL; LangGraph checkpoints in PostgreSQL |
| Next.js/Node.js | Discovery, confirmation, conversation, citations, sidebar, server-side API proxy | Browser state only; authoritative chats remain in PostgreSQL |
| PostgreSQL 17 | Chats, images, runs, replay events, evidence/trace, plant-name index, reference definitions | Docker volume `impark-major-project_postgres-data` |
| Neo4j `2026.09.0` | Read-only medicinal-plant graph | Separate `neo4j-dev` container, volume `neo4j_dev_data` |
| Qdrant `v1.13.6` | Plant-name semantic vectors and separate image-reference vectors | Docker volume `impark-major-project_qdrant-data` |
| Ollama on Windows | Local response and optional intent model (`gemma4:e4b` in the current demo) | Ollama's **host** model cache, not a Docker volume |
| Redis 7 | Optional transient adapter | No Redis volume in the current Compose file; not required by the demo launcher |

The three local Docker images above were read from the running development containers. `docker-compose.yml` supplies PostgreSQL/Qdrant; `scripts/demo.ps1` deliberately uses the separate container named `neo4j-dev`. The optional Compose Neo4j service is version-aligned but is **not** the container the launcher starts. Docker images contain software; volumes contain database data. Neither contains `data/image/xception_model.keras` or the image dataset. Ollama also needs its own model pull.

The current graph handoff should produce the previously checked graph size of **4,075 nodes and 11,697 relationships**. Verify the imported copy instead of assuming a started container means the graph was restored.

## 2. Repository map

The following are ownership boundaries and the files teammates will most often edit. `__init__.py` files make packages importable; they do not introduce additional agents. Keep FastAPI routes thin, retain typed agent results, and do not put graph queries into the response model.

### Root and scripts

| Path | Purpose |
| --- | --- |
| `AGENTS.md` and other project notes | Architecture and development rules. The root `.gitignore` currently excludes Markdown files except files named `README.md`; this handbook is named accordingly so Git can track it. |
| `pyproject.toml` | Python 3.12+ package and dependency groups: runtime, `dev`, and optional TensorFlow `image`. It also defines pytest, Ruff and mypy settings. |
| `requirements-dev.lock` | Captured development package versions; the documented installation command uses `pyproject.toml` because the image extra is separate. |
| `frontend/package.json`, `frontend/package-lock.json` | Next.js/npm scripts and pinned frontend dependency resolution. Use `npm ci` for a teammate install. |
| `docker-compose.yml` | Local PostgreSQL, Qdrant, optional Neo4j/Redis and an optional backend container definition. The demo launcher starts only PostgreSQL/Qdrant through Compose. |
| `Dockerfile` | Minimal backend container build; the supported local demo runs Python on Windows so it can reach host Ollama and image artifacts without extra container mounts. |
| `.env.example`, `frontend/.env.example` | Safe configuration templates. Actual `.env` and `frontend/.env.local` contain machine-specific values and are ignored by Git. |
| `scripts/demo.ps1` | Starts/stops only recognized IMPARK listeners on ports 8000/3000, starts PostgreSQL/Qdrant unless skipped, builds/starts Next.js, then runs readiness checks. `-Restart`, `-SkipDocker`, `-SkipWarmup`, and `-DevFrontend` are supported. |
| `scripts/export_team_handoff.ps1` | Verified cold handoff exporter for the exact running local containers/volumes. Checks free space and assets, stops only recognized IMPARK listeners, snapshots stopped volumes, saves images/assets, verifies archives and checksums, then restarts databases and the demo. Refuses to overwrite an existing handoff. |
| `scripts/demo_warmup.py` | Checks backend, configured stores, autocomplete, image capability and makes a small Ollama generation request. A ready message is not a claim of model accuracy. |
| `scripts/configure_local_search.py` | Helper for setting up the local search configuration. |
| `scripts/smoke_backend.py` | Backend smoke checks. |
| `training/image/train_model.py` | Preserved training recipe for the supplied image model; inference does not retrain weights. |

### Backend startup, API, and durable chat

| Path | Purpose |
| --- | --- |
| `backend/__main__.py`, `backend/runtime.py` | `python -m backend` entry point and Windows-compatible async event-loop setup. |
| `backend/main.py` | FastAPI app factory and lifespan. Validates config, opens shared clients, installs real agent providers, attaches the checkpointer/trace sink, enforces a single-process PostgreSQL lease, and closes resources. Startup checks stores but does not migrate, seed or index them. |
| `backend/config/settings.py` | Pydantic settings for API, budgets, image, Ollama and safety limits; combines Neo4j and search settings. Rejects invalid combinations. |
| `backend/api/routes/platform.py` | Production `/api/v1` chat, operation, autocomplete, evidence and health-adjacent contracts. It delegates to services rather than choosing agents. |
| `backend/api/routes/images.py` | Chat image upload/fetch handling. |
| `backend/api/routes/conversations.py` | Separate development-only `/dev` synchronous surface; frontend should use `/api/v1`. |
| `backend/api/schemas/`, `backend/contracts/` | Pydantic request/response contracts and internal typed actions, agent results, evidence and response packets. |
| `backend/api/dependencies/` | Dependency injection and authorization helpers for the route surfaces. |
| `backend/api/streaming.py`, `backend/services/live.py` | SSE formatting and live progress publication. Durable event replay is stored separately. |
| `backend/api/middleware.py` | Correlation IDs, logging and safe error boundaries. |
| `backend/api/export_contracts.py` | Regenerates `frontend/contracts/openapi.json` and stream-event schema after API changes. |
| `backend/services/runs.py` | Durable operation manager: idempotency, lifecycle, cancellation/resume, single active operation per chat, SSE events and deletion coordination. |
| `backend/services/conversations.py` | Domain service for starting/resuming a turn and presenting public session state. |
| `backend/services/chat_images.py`, `backend/services/images.py` | Image ownership, validation and storage boundaries. |
| `backend/database/postgres/chat.py` | `app_session`, message, operation, event and image repository. This is why chats survive browser reloads. |

### Harness, agents, evidence and response

| Path | Purpose |
| --- | --- |
| `backend/state/models.py`, `backend/state/goals.py` | Session mode, active plant, objectives, beliefs, evidence, context, action history, budgets and termination state. |
| `backend/orchestrator/graph.py` | Cyclic LangGraph runtime and checkpoint/clarification interrupt routing. |
| `backend/orchestrator/orchestrator.py` | Custom Harness: observe → assess → decide → dispatch → evaluate/update → replan or respond. The harness is **not** a fourth specialized agent. |
| `backend/orchestrator/actions.py`, `decision.py`, `policy.py` | Finite action registry, heuristic ranking and deterministic eligibility/plant-lock authority. |
| `backend/orchestrator/execution.py` | Invokes only the eligible specialized agent and wraps results as typed observations/failures. |
| `backend/orchestrator/clarification.py`, `recovery.py`, `termination.py` | Same-lineage resume, loop/retry detection and bounded end states. |
| `backend/agents/text/agent.py`, `interpretation.py`, `semantic_intent.py`, `intent_model.py` | Natural-language intent and follow-up interpretation. Optional model suggestions are checked against typed, supported graph-query intents. |
| `backend/agents/text/search.py`, `resolver.py`, `catalog.py`, `embeddings.py` | Exact/alias/FTS/trigram/fuzzy/semantic plant-name candidates, ambiguity handling, catalog structures and off-loop embeddings. |
| `backend/agents/image/model.py`, `preprocessing.py`, `quality.py`, `inference.py` | Supplied Xception leaf model, image normalization and quality checks; one forward pass supplies 40-class scores and feature vector. |
| `backend/agents/image/retrieval.py`, `ranking.py`, `agent.py`, `providers.py` | Qdrant image neighbors, deterministic CNN/vector fusion, typed image observation and provider interfaces. Identification is still a suggestion until user confirmation. |
| `backend/agents/image/admin.py`, `build_index.py`, `evaluate.py` | Explicit offline feature extraction, image collection build and comparison report; never run as web-startup side effects. |
| `backend/agents/graph/agent.py`, `retrieval.py` | Typed, allow-listed, bounded, parameterized, read-only plant-scoped Cypher; builds evidence paths, gaps and contradictions. |
| `backend/agents/common/` | Shared typed agent bundle/contracts and controlled plant-part vocabulary used across agents. |
| `backend/evidence/evaluator.py`, `context_builder.py` | Updates beliefs/evidence without letting generation upgrade an evidence class; builds the deterministic final-response packet. |
| `backend/evidence/reference.py`, `reference_import.py` | Optional PostgreSQL cache of verified MeSH term definitions and explicit importer; term definitions are not proof of a plant treatment effect. |
| `backend/llm/provider.py`, `ollama.py` | Provider interface and bounded Ollama HTTP calls. Model/base URL are configuration values. |
| `backend/llm/verbalize.py`, `narrative.py`, `concise.py`, `part_glossary.py` | Allow-listed factual wording, simple term/relationship explanations and deterministic fallback prose. |
| `backend/llm/knowledge_explanation.py`, `guarded.py`, `grounded.py` | General model-background explanation validator, guarded model response/streaming, and fully deterministic provider. Cited retrieved facts and uncited model background remain distinct. |
| `backend/trace/recorder.py`, `models.py`, `instrumentation.py` | Non-blocking domain trace queue, typed events and technical spans/correlation. Trace persistence failure must not fail a turn. |
| `backend/evaluation/` | Discovery evaluation, harness benchmarks and trace audit. See its README for limitations. |

### Database and frontend

| Path | Purpose |
| --- | --- |
| `backend/database/neo4j/config.py`, `driver.py`, `client.py` | Environment validation, one reusable official-driver lifecycle and explicit read/write/session operations. |
| `backend/database/neo4j/queries.py`, `medicinal.py`, `repository.py`, `models.py` | Domain graph queries, typed records and repository methods, separate from the connection layer. |
| `backend/database/neo4j/diagnostics.py`, `__main__.py` | Read-only health, schema and sample-plant checks. |
| `backend/database/postgres/client.py`, `persistence.py`, `checkpoints.py` | Async SQL client, durable session/trace persistence and LangGraph checkpoint connection. |
| `backend/database/postgres/search.py`, `backend/database/search_sync.py` | PostgreSQL name index and explicit projection of Neo4j plant/alias records into PostgreSQL/Qdrant. |
| `backend/database/postgres/migrate.py`, `migrations/001`–`004` | Explicit versioned schema setup: search; entity catalog; chat API; reference notes. Do not treat web startup as migration. |
| `backend/database/qdrant/client.py`, `repository.py` | Qdrant connection, collection validation and bounded vector operations. Text and image use different collections. |
| `backend/database/search_admin.py`, `search_config.py` | `migrate`, `sync`, `health` commands and local/cloud store configuration. |
| `backend/database/redis/repository.py`, `database/memory.py` | Optional transient and in-memory/development adapters. PostgreSQL is the durable demo source. |
| `frontend/app/`, `frontend/next.config.ts` | Next.js routes: landing page, `/chat/[id]` and server-side `/api/v1` reverse proxy. |
| `frontend/src/App.tsx`, `api.ts`, `types.ts` | Chat state, route restoration, run/SSE/retry handling, API calls and TypeScript contracts. |
| `frontend/src/components/Discovery.tsx`, `Clarification.tsx`, `Conversation.tsx` | Discovery form, interrupt/resume choice and active-plant chat transcript/composer. |
| `frontend/src/components/Evidence.tsx`, `Sidebar.tsx` | Citation-linked evidence panel and full paginated chat list/archive/delete UI. A direct source link is shown only when attached to that citation. |
| `frontend/src/sessionPages.mjs`, `frontend/api/client.mjs` | Sidebar page collection with stale-refresh rejection; transport client with SSE framing/idempotency. |
| `frontend/src/styles.css`, `frontend/contracts/` | Responsive design and exported machine-readable API/SSE contracts. |
| `tests/` | Unit, text, graph, orchestration, API, integration, evaluation and opt-in live tests. Tests marked live need configured local stores. |

### Models, graph schema, and database tables

The name-search embedding provider uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` through FastEmbed and produces 384-dimensional vectors in `plant_names_v1`. PostgreSQL is still the exact/FTS/trigram name index and stores the active search generation. The text intent path first interprets supported query types from words and context, and can request a bounded Ollama suggestion; the returned type is validated before the harness can act. This model is **not** an extra agent or an authority to issue Cypher.

The image model is the supplied `data/image/xception_model.keras`, not a generic Ollama vision call. It outputs 40 leaf-class scores plus a normalized 2048-dimensional feature vector. `data/image/class_indices.json` and `label_correction.json` map output positions to the supported labels; the Qdrant image collection `plant_images_v1` holds reference features for CNN/vector fusion. `index_manifest.json` binds the model/dataset version to the collection. `features.npz` is a reproducible extraction cache. Because the original class mapping swapped two labels, copying only the `.keras` file without the corrected class map is unsafe. The 2,507 source images are in the ignored `data/image/dataset/` directory on the inspected machine.

The final response model is a separate Ollama model selected by `LLM_MODEL`; this demo currently uses `gemma4:e4b`. It receives the already-approved response context. For ordinary answers it can phrase supplied cited facts; for explicit “explain” follow-ups it can add short, clearly separated general scientific background. Validation rejects unsupported plant-specific claims, fabricated measurements/URLs and internal execution language before sending text. If generation fails, the deterministic grounded provider remains available. This is a hallucination-reduction boundary, not independent verification of every pretrained statement.

The source Neo4j graph includes the actual labels `PlantDetails`, `PlantAlias`, `PlantPart`, `Phytochemicals`, `TherapeuticUse`, `Bioactivity`, `Protein_Target` and `Document`, with known relationships `HAS_ALIAS`, `HAS_PART`, `CONTAINS`, `USED_FOR`, `HAS_BIOACTIVITY`, `MEASURED_ON` and `REPORTED_IN`. Graph retrieval follows code-owned paths for the requested query type, anchored at the locked `PlantDetails` plant. No user/model string becomes a raw Cypher statement. `Document` links are not invented for every graph record; a ChEMBL document ID yields a link only when the retrieved path actually reaches that document.

PostgreSQL's versioned migrations define these main data groups:

| Tables | What they contain |
| --- | --- |
| `search_generation`, `search_plant`, `search_name`, `search_entity` | Active/staged search projection and stable plant/entity names. `search_name` has normalized aliases, alias type/language, FTS and trigram indexes. |
| `app_session`, `app_turn` | Durable chat state and completed/interrupted turn snapshots. The state contains the locked plant and conversation mode. |
| `api_operation`, `api_event`, `chat_message`, `chat_image` | Idempotent asynchronous operations, replayable SSE events, transcript and uploaded image bytes. |
| LangGraph checkpoint tables | Resume and clarification state, created by explicit checkpoint setup during `search_admin migrate`. |
| `domain_trace`, `text_evaluation` | Non-blocking research traces and evaluation reports. |
| `reference_note` | Optional verified MeSH definitions, not a second medicinal-plant database. |

Qdrant and PostgreSQL search records share a generation identifier. Restore them from the same snapshot or rebuild with one explicit `sync`; mixing an old Qdrant volume with a new PostgreSQL generation can break semantic search. Redis is optional and has no durable data contract here.

### One request from browser to answer

1. Next.js creates a durable chat with `POST /api/v1/conversations`. `GET /api/v1/capabilities` tells the UI whether image identification is configured. The browser may query autocomplete but must not decide that a candidate is the final plant.
2. The user submits text, a registered image ID, or a selected candidate with `POST /api/v1/conversations/{sid}/turns`. FastAPI creates an idempotent operation and stores the pending messages. The UI listens to that operation's replayable SSE URL; a reconnect uses the last event sequence and reads the durable run status.
3. The LangGraph control loop observes the latest state, assesses goals, enumerates eligible actions, decides, invokes the selected specialized agent and evaluates its typed observation. The loop can retrieve more evidence, ask a clarification, retry within budgets, or stop. A clarification interrupts the checkpoint and resumes the same chat when answered.
4. Once the plant identity is confirmed, `state.active_plant` and the lock persist in PostgreSQL. Follow-up wording such as “What about the leaves?” uses that context; an attempt to switch plants is rejected or redirected to a new chat. The graph agent retrieves only plant-scoped allow-listed paths relevant to the interpreted question.
5. Evidence remains separated by text, image and graph origin, with provenance and evidence class. The harness builds a deterministic `response_context` with selected cited facts and gaps. The final response provider may write a readable answer and optionally add labeled general scientific context, but cannot turn a traditional/preclinical association into clinical proof.
6. Server-side citation markers map to evidence IDs stored with the run. The UI opens the exact record for `[n]`; it does not substitute an unrelated PubMed search for an IMPPAT/ChEMBL source. Messages, evidence snapshots, operation events and traces remain available after reload. The sidebar follows all chat-list pages so older chats are not silently hidden.

Meaningful domain events, decisions, agent calls, contradictions, clarifications, response context and LLM lifecycle events are enqueued to `backend/trace/recorder.py` and persisted by the background sink. The control path does not wait for PostgreSQL trace writes. Evaluation commands under `backend/evaluation/` consume these traces and frozen question sets. The trace audit checks ordering, correlation and action eligibility; it does not claim that the LLM's pretrained scientific knowledge has been independently verified. The full endpoint and error table lives in [the frontend README](../frontend/README.md).

## 3. Prerequisites for a teammate on Windows

Install **Python 3.12 or newer** from [Python.org for Windows](https://www.python.org/downloads/windows/), a current **Node.js LTS with npm** from [Node.js downloads](https://nodejs.org/en/download), **Docker Desktop using Linux containers/WSL 2**, and **Ollama for Windows**. Docker's [Windows installation guide](https://docs.docker.com/desktop/setup/install/windows-install/) gives the supported Windows/WSL requirements. Install Ollama from its [official Windows download](https://ollama.com/download/windows); the [Gemma 4 model page](https://ollama.com/library/gemma4) documents the `e4b` tag. Do not run an arbitrary downloaded PowerShell installer just because a README mentions it; use the official installer page. After installation, open Docker Desktop and wait for its engine to become ready.

```powershell
py --version
node --version
npm --version
docker version
docker compose version
ollama --version
```

The current Ollama `gemma4:e4b` package is several GB. A 4 GB VRAM card may offload part of it to system RAM, so leave enough RAM and disk space and benchmark latency on each teammate's machine. Ollama is installed on the **Windows host**, not in this project's Compose stack. The current image model runs through TensorFlow on the Python host; it has different dependencies from Ollama. The first semantic-name search can also download its embedding model into `data/model-cache` unless that cache is transferred.

Clone the repository into any local path. Commands below assume PowerShell is already at the repository root; they avoid the original developer's `D:` drive path.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e '.[dev,image]'
Push-Location frontend
npm ci
Copy-Item .env.example .env.local
Pop-Location
Copy-Item .env.example .env
```

If a teammate does not need image inference yet, `-e '.[dev]'` avoids TensorFlow, and `IMAGE_ENABLED=false` must remain set. The image model/dataset are not downloaded by pip. If `py` selects an unsuitable Python, use a specific installed interpreter to create `.venv` and confirm `.\.venv\Scripts\python.exe --version` before installing.

### Configure `.env` safely

Edit `.env` privately. Use the **same** PostgreSQL credentials for `POSTGRES_*` (container initialization) and `DATABASE_URL` (Python). The Neo4j password for a restored volume must be the credential that actually works with the restored graph; changing `NEO4J_AUTH` alone does not reset an initialized graph's password. Never commit `.env`, `frontend/.env.local`, a password-bearing connection URI, or a transfer archive. A local example of the **non-secret** values is:

```dotenv
COMPOSE_PROJECT_NAME=impark-major-project
APPLICATION_ENV=development
ENABLE_DEVELOPMENT_API=true
CORS_ORIGINS=["http://127.0.0.1:3000","http://localhost:3000"]
NEO4J_ENABLED=true
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_DATABASE=neo4j
TEXT_SEARCH_ENABLED=true
POSTGRES_PORT=15432
QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=plant_names_v1
IMAGE_COLLECTION=plant_images_v1
TEXT_SEMANTIC_ENABLED=true
IMAGE_ENABLED=true
IMAGE_MODEL_PATH=data/image/xception_model.keras
IMAGE_CLASSES_PATH=data/image/class_indices.json
IMAGE_MANIFEST_PATH=data/image/index_manifest.json
LLM_PROVIDER=ollama
LLM_MODEL=gemma4:e4b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Fill `NEO4J_PASSWORD`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` and `DATABASE_URL=postgresql://<user>:<URL-encoded-password>@127.0.0.1:15432/<database>` locally. URL-encode reserved password characters in `DATABASE_URL`. `QDRANT_API_KEY` is blank for the local container but can be set for a hosted instance. `API_KEY` is optional only for the explicit local development bypass; if set, put the same value in `frontend/.env.local` as `BACKEND_API_KEY`. `BACKEND_URL=http://127.0.0.1:8000` is the default frontend proxy destination. For a cloud store, change only the environment URI/key fields; keep code unchanged. Never run local data import/sync commands against production accidentally.

## 4. Two valid ways to provision data

Choose **one** route before starting the web servers:

1. **Fresh stores:** start empty PostgreSQL/Qdrant and a populated Neo4j graph, run the explicit migration and Neo4j→search sync, then optionally build the image index. This does **not** invent the medicinal graph; a teammate still needs the approved Neo4j dataset and image assets.
2. **Transfer the developer's cold volumes:** restore all three database volumes together from one stopped-system snapshot. This preserves the graph, search generation, vector collections, chats, evidence and traces at that snapshot. Skip `sync` on first boot; use `migrate` only if the checked-out code contains a newer unapplied migration. Transfer image model/dataset separately. This is the quickest exact demo handoff.

### Fresh-store route

Set the secret values in `.env` first. The launcher expects a container named `neo4j-dev`, so create that separate container when starting from an empty graph or restoring its volume:

```powershell
docker compose --profile stores up -d postgres qdrant
# Choose your own secret locally; do not paste it into a shared shell transcript.
$env:NEO4J_AUTH = 'neo4j/<your-local-password>'
docker run -d --name neo4j-dev -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 --mount 'type=volume,source=neo4j_dev_data,target=/data' -e NEO4J_AUTH neo4j:2026.09.0
```

An empty Neo4j container is **not** a usable IMPARK graph. Load an authorized dataset by its own documented import method, then check it with `python -m backend.database.neo4j inspect`. The project does not automatically restore or seed Neo4j. Once the graph is ready:

```powershell
.\.venv\Scripts\python.exe -m backend.database.neo4j health
.\.venv\Scripts\python.exe -m backend.database.neo4j inspect
.\.venv\Scripts\python.exe -m backend.database.search_admin migrate
.\.venv\Scripts\python.exe -m backend.database.search_admin sync
.\.venv\Scripts\python.exe -m backend.database.search_admin health
# Optional, requires network access to the National Library of Medicine:
.\.venv\Scripts\python.exe -m backend.evidence.reference_import --limit 500
```

`migrate` applies versioned PostgreSQL migrations, checkpoint setup and Qdrant collection provisioning. `sync` copies only the plant/alias search projection from Neo4j into PostgreSQL and Qdrant; it does not copy the entire graph. The search index and image vectors are distinct. Run image indexing only after placing the supplied model and `data/image/dataset/` in the expected paths:

```powershell
.\.venv\Scripts\python.exe -m backend.agents.image.admin extract --dataset data/image/dataset --model data/image/xception_model.keras --classes data/image/class_indices.json --output data/image/features.npz
.\.venv\Scripts\python.exe -m backend.agents.image.build_index --cache data/image/features.npz --manifest data/image/index_manifest.json
```

### Cold-volume transfer route: exporter

These are **instructions to run intentionally**, not actions performed by the application. Use the exact Git commit that produced the source machine's search schema and image manifest; commit pending code first and record `git rev-parse HEAD` in the handoff message. The source machine's inspected volume names are:

| Container | Source volume | Destination inside container | Matching image |
| --- | --- | --- | --- |
| `neo4j-dev` | `neo4j_dev_data` | `/data` | `neo4j:2026.09.0` |
| `impark-major-project-postgres-1` | `impark-major-project_postgres-data` | `/var/lib/postgresql/data` | `postgres:17` |
| `impark-major-project-qdrant-1` | `impark-major-project_qdrant-data` | `/qdrant/storage` | `qdrant/qdrant:v1.13.6` |

The requested snapshot **was actually created on 17 October 2026** at `backups/team-handoff/` in this checkout. The exporter checked the exact containers/volumes above, paused the matching IMPARK frontend/backend, stopped all three databases, saved the files below, tested that every archive is readable, wrote five SHA-256 entries and restarted the demo. `gemma4:e4b` warmup and all store readiness checks passed after restart; read-only Neo4j counts were **4,075 nodes and 11,697 relationships**. The files are ignored by Git and must be transferred separately.

| File now present in `backups/team-handoff/` | Bytes | Receiver use |
| --- | ---: | --- |
| `database-images.tar` | 631,387,136 | `docker image load`; contains `neo4j:2026.09.0`, `postgres:17`, `qdrant/qdrant:v1.13.6`, `alpine:3.20`. |
| `neo4j-data.tgz` | 3,106,905 | Restore into a new `neo4j_dev_data` volume; this is the graph data, not the Neo4j image. |
| `postgres-data.tgz` | 32,543,906 | Restore into a new `impark-major-project_postgres-data` volume. |
| `qdrant-data.tgz` | 84,758,965 | Restore into a new `impark-major-project_qdrant-data` volume. |
| `image-assets.tgz` | 746,600,671 | Extract at the repo root; contains `data/image/` model, dataset, feature cache and manifests. |
| `SHA256.txt` | 421 | Five hashes for verifying the archives before restoring. |

For a new snapshot, let active runs finish, then from the repository root run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\export_team_handoff.ps1 -Destination 'backups\team-handoff-next'
```

Use a new destination because the script refuses to replace the existing handoff. It briefly takes the local demo offline and restarts it, even if an archive step fails. Verify the current container names with `docker ps` if the setup changes. The following manual block shows the underlying volume/image steps; teammates can use the script instead of copying this long block:

```powershell
$backupRoot = Join-Path (Get-Location) 'backups\team-handoff'
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
docker pull alpine:3.20
if ($LASTEXITCODE -ne 0) { throw 'Could not get the archive helper image' }
$volumes = @(
  @{ Name='neo4j_dev_data'; File='neo4j-data.tgz' },
  @{ Name='impark-major-project_postgres-data'; File='postgres-data.tgz' },
  @{ Name='impark-major-project_qdrant-data'; File='qdrant-data.tgz' }
)
foreach ($item in $volumes) {
  docker volume inspect $item.Name *> $null
  if ($LASTEXITCODE -ne 0) { throw "Expected volume is missing: $($item.Name)" }
}
try {
  docker stop neo4j-dev impark-major-project-postgres-1 impark-major-project-qdrant-1
  if ($LASTEXITCODE -ne 0) { throw 'A database container did not stop; do not take a hot file snapshot' }
  foreach ($item in $volumes) {
    docker run --rm --mount "type=volume,source=$($item.Name),target=/source,readonly" --mount "type=bind,source=$backupRoot,target=/backup" alpine:3.20 tar -C /source -czf "/backup/$($item.File)" .
    if ($LASTEXITCODE -ne 0) { throw "Backup failed for $($item.Name)" }
  }
  docker image save --output (Join-Path $backupRoot 'database-images.tar') neo4j:2026.09.0 postgres:17 qdrant/qdrant:v1.13.6 alpine:3.20
  if ($LASTEXITCODE -ne 0) { throw 'Docker image export failed' }
  tar.exe -czf (Join-Path $backupRoot 'image-assets.tgz') -C . data/image
  if ($LASTEXITCODE -ne 0) { throw 'Image artifact export failed' }
  Get-ChildItem $backupRoot -File | Where-Object Name -ne 'SHA256.txt' | Get-FileHash -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  $([IO.Path]::GetFileName($_.Path))" } | Set-Content (Join-Path $backupRoot 'SHA256.txt')
} finally {
  docker start neo4j-dev impark-major-project-postgres-1 impark-major-project-qdrant-1
}
```

`image-assets.tgz` includes the supplied 157 MB Xception weights, 2,507 dataset files and feature cache from the inspected development machine. The dataset and model may have separate sharing/licensing conditions; confirm permission to distribute them to teammates. `data/model-cache/` is optional and can be copied privately if teammates cannot download the embedding model. Ollama models are **not** in the Docker archives; each teammate can run `ollama pull gemma4:e4b`. Transfer the archives by a private file-sharing method, separate from Git/GitHub. They contain chat history, uploaded images, traces and possibly research material; treat them as sensitive. Send working database passwords through a separate secure channel. The archives are ignored under `backups/`.

Docker's official [volume backup/restore guide](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes) describes this tar-through-helper-container pattern. [Image save/load](https://docs.docker.com/reference/cli/docker/image/load/) transfers software tags separately from volume contents. Raw PostgreSQL volumes are tied to the **same major server version** and platform; `postgres:17` on both machines is required. For a more portable database transfer, use a PostgreSQL logical dump/restore instead. Never restore a raw volume over a running database.

### Cold-volume transfer route: receiver

On a **fresh** teammate Docker installation, receive the **entire `team-handoff` folder** containing the six files in the table, check out the shared code commit, install dependencies, set `COMPOSE_PROJECT_NAME=impark-major-project` in `.env`, and place the handoff directory under ignored `backups/` at the repo root. If they store it elsewhere, change only `$backupRoot` below. **Do not start Compose or create data containers before this restore.** The following verifies all five hashes, loads the exact images, creates only absent volumes, restores the three cold database archives, then extracts the image assets. It deliberately refuses to overwrite an existing volume:

```powershell
$backupRoot = (Resolve-Path '.\backups\team-handoff').Path
foreach ($line in Get-Content (Join-Path $backupRoot 'SHA256.txt')) {
  if ($line -notmatch '^([A-Fa-f0-9]{64})  (.+)$') { throw 'Invalid SHA256 manifest line' }
  $expected = $Matches[1]
  $file = $Matches[2]
  $actual = (Get-FileHash (Join-Path $backupRoot $file) -Algorithm SHA256).Hash
  if ($actual -ne $expected) { throw "Hash mismatch: $file" }
}
docker image load --input (Join-Path $backupRoot 'database-images.tar')
if ($LASTEXITCODE -ne 0) { throw 'Docker image import failed' }
$volumes = @(
  @{ Name='neo4j_dev_data'; File='neo4j-data.tgz' },
  @{ Name='impark-major-project_postgres-data'; File='postgres-data.tgz' },
  @{ Name='impark-major-project_qdrant-data'; File='qdrant-data.tgz' }
)
foreach ($item in $volumes) {
  docker volume inspect $item.Name *> $null
  if ($LASTEXITCODE -eq 0) { throw "Refusing to overwrite existing volume $($item.Name)" }
  docker volume create $item.Name | Out-Null
  docker run --rm --mount "type=volume,source=$($item.Name),target=/target" --mount "type=bind,source=$backupRoot,target=/backup,readonly" alpine:3.20 tar -C /target -xzf "/backup/$($item.File)"
  if ($LASTEXITCODE -ne 0) { throw "Restore failed for $($item.Name)" }
}
tar.exe -xzf (Join-Path $backupRoot 'image-assets.tgz') -C .
if ($LASTEXITCODE -ne 0) { throw 'Image artifact restore failed' }
```

Now set the **restored PostgreSQL user/database/password** and **restored Neo4j credential** in the private `.env`. A volume may already have database credentials and schema, so setting new `POSTGRES_*` or `NEO4J_AUTH` values does not reset them. Confirm the source and receiver use compatible CPU architecture and the identical database image versions. Then start the same containers:

```powershell
docker compose --profile stores up -d postgres qdrant
$env:NEO4J_AUTH = 'neo4j/<restored-database-password>'
docker run -d --name neo4j-dev -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 --mount 'type=volume,source=neo4j_dev_data,target=/data' -e NEO4J_AUTH neo4j:2026.09.0
.\.venv\Scripts\python.exe -m backend.database.neo4j inspect
.\.venv\Scripts\python.exe -m backend.database.search_admin health
```

Check the graph counts and collection names. The restored PostgreSQL search generation must correspond to the restored Qdrant points; transferring all three volumes from the **same** stopped snapshot preserves that relationship. Do not run `sync` merely because the transfer finished: it creates a new search generation and can take time or produce a mismatch if the graph or embedding model differs. If code has a newer migration, run `search_admin migrate` explicitly after making a second backup. If `data/image/` or the Qdrant image collection is missing, run the explicit image extraction/index commands above. If you choose to rebuild instead of restore a volume, document that decision and rebuild its dependent index.

Always specify `postgres qdrant` on the Compose `up` command for this workflow. Running `docker compose --profile stores up -d` without service names would also attempt the optional Compose Neo4j service, creating a second Neo4j container that competes with `neo4j-dev` for the same host ports.

## 5. Ollama and launch

After installing Ollama for Windows, download and check the same model configured in `.env`:

```powershell
ollama pull gemma4:e4b
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags | Select-Object -ExpandProperty models | Select-Object name
.\.venv\Scripts\python.exe -m backend.llm.admin warm
```

If the teammate's hardware cannot serve Gemma within the configured time budget, use `LLM_PROVIDER=grounded` for deterministic sourced wording while diagnosing performance; that changes response style but does not require a code change. Do not silently use a cloud model for a local demo. The image agent is independent of Ollama. Ollama also assists optional intent interpretation; deterministic validation still decides whether a proposed intent is supported.

With the stores and model ready, the one-command production-style demo is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo.ps1 -Restart
```

The launcher checks PostgreSQL, Qdrant, Neo4j, autocomplete, image classifier and the Ollama model. It rebuilds Next.js in production mode and opens services at `http://127.0.0.1:8000` and `http://127.0.0.1:3000`. It does **not** migrate/import data or start an absent `neo4j-dev`. For day-to-day frontend work, run the backend (`.\.venv\Scripts\python.exe -m backend`) and `npm run dev` from `frontend/` in separate terminals. Use `-SkipDocker` only when data stores are already running. See `data/demo-backend.err.log` and `data/demo-frontend.err.log` if readiness fails.

## 6. Verify and troubleshoot the handoff

```powershell
.\.venv\Scripts\python.exe -m backend.database.neo4j health
.\.venv\Scripts\python.exe -m backend.database.neo4j inspect
.\.venv\Scripts\python.exe -m backend.database.search_admin health
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/capabilities
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m mypy backend
Push-Location frontend
npm test
npm run typecheck
npm run build
Pop-Location
```

Run the UI flow: search for a plant name, confirm the intended candidate, see it locked in the header, ask a follow-up without repeating its name, open `[1]` and verify it maps to that answer's actual evidence, create/archive/delete a chat, then reload. The Sources panel does **not** substitute a PubMed search for an IMPPAT or ChEMBL citation. A source with no direct document URL says so. Image-only identification requires the transferred image assets and index and still needs user confirmation.

| Symptom | Check |
| --- | --- |
| `neo4j-dev` missing or graph count zero | Restore the Neo4j volume and use the separate container name expected by the launcher. A fresh image alone has no graph. |
| Neo4j authentication fails after restore | Use the actual persisted graph credential; `NEO4J_AUTH` does not reset a restored password. |
| PostgreSQL password fails | `POSTGRES_*` is initialization-only on an existing volume; use the restored database credential in `DATABASE_URL`. |
| Qdrant collection missing/mismatch | Confirm matching Qdrant volume and `QDRANT_COLLECTION`/`IMAGE_COLLECTION`, or rebuild the appropriate collection explicitly. |
| Name autocomplete missing | Check active PostgreSQL search generation, `TEXT_SEARCH_ENABLED`, graph availability and `search_admin health`; on a fresh installation run `migrate` then `sync`. |
| Image classifier unavailable | Confirm TensorFlow extra, model/class/manifest files, dataset fingerprint and image collection. Set `IMAGE_ENABLED=false` until those are present. |
| Ollama times out | Check `ollama list`, port 11434, configured tag, available RAM/VRAM and model warmup. Keep `LLM_TIMEOUT_SECONDS` below `ACTION_TIMEOUT_SECONDS`. |
| Backend says another process owns the database | Stop the earlier backend; the MVP intentionally uses one worker and a PostgreSQL advisory lease. |
| Older chats appear after deleting visible ones | Update to the frontend that loads all sidebar pages; deleting a visible subset of an old 30-item client did not delete hidden older sessions. |

The project keeps one plant per chat, a bounded action/retry budget and evidence-class limits. General LLM background is helpful context, **not independently source-verified**. Do not interpret model fluency, the 40-class image training-set score, or a graph link as clinical proof.
