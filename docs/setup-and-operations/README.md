# Teammate setup: from handoff to a running demo

This guide is for **Windows PowerShell**. Run every command from the repository root unless a step says otherwise. The fastest path is to restore the six files in `backups/team-handoff/` made by `scripts/export_team_handoff.ps1`. That archive set contains the three database volumes, Docker images, and image-model assets. It does **not** contain `.env` passwords, the Ollama model cache, Python packages, or npm packages.

```mermaid
flowchart LR
    ZIP[Private team handoff folder] --> CHECK[SHA-256 verification]
    CHECK --> N[neo4j_dev_data]
    CHECK --> P[impark-major-project_postgres-data]
    CHECK --> Q[impark-major-project_qdrant-data]
    CHECK --> I[data/image assets]
    N --> NC[neo4j-dev container]
    P --> PC[Compose postgres]
    Q --> QC[Compose qdrant]
    NC --> API[FastAPI]
    PC --> API
    QC --> API
    I --> API
    O[Ollama on Windows] --> API
    API --> UI[Next.js frontend]
```

## A. Restore the supplied handoff (recommended)

### 1. Install and obtain the files

Install Python 3.12+, Node.js/npm, Docker Desktop with **Linux containers**, and Ollama for Windows. Start Docker Desktop and wait for its engine to be ready. Clone the **same Git revision** as the exporter used. Put the transferred files directly under `backups/team-handoff/`:

```text
backups/team-handoff/
  SHA256.txt
  database-images.tar
  neo4j-data.tgz
  postgres-data.tgz
  qdrant-data.tgz
  image-assets.tgz
```

The handoff folder is ignored by Git and should be transferred privately. Check that it is complete before any restore:

```powershell
Set-Location 'PATH\TO\impark-major-project'
Get-ChildItem .\backups\team-handoff\ | Select-Object Name,Length
docker version
docker compose version
py --version
node --version
ollama --version
```

### 2. Install project dependencies

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

If `.env` or `frontend/.env.local` already exists, edit it instead of overwriting it. `npm ci` uses the checked-in lock file. The image extra installs the dependencies needed to load the supplied Xception model.

### 3. Fill in `.env` **before** starting containers

Open the root `.env` in a text editor and set at least the following values. These are examples with placeholders, **not** the source machine's credentials:

```dotenv
COMPOSE_PROJECT_NAME=impark-major-project
APPLICATION_ENV=development
ENABLE_DEVELOPMENT_API=true

NEO4J_ENABLED=true
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=REPLACE_WITH_EXPORTED_GRAPH_PASSWORD
NEO4J_DATABASE=neo4j

TEXT_SEARCH_ENABLED=true
DATABASE_URL=postgresql://REPLACE_USER:REPLACE_PASSWORD@127.0.0.1:15432/REPLACE_DB
POSTGRES_USER=REPLACE_USER
POSTGRES_PASSWORD=REPLACE_PASSWORD
POSTGRES_DB=REPLACE_DB
POSTGRES_PORT=15432
QDRANT_URL=http://127.0.0.1:6333
TEXT_SEMANTIC_ENABLED=true

AGENT_MAIN_MODEL_PROVIDER=ollama
AGENT_MAIN_MODEL=gemma4:e4b
OLLAMA_BASE_URL=http://127.0.0.1:11434

IMAGE_ENABLED=true
IMAGE_MODEL_PATH=data/image/xception_model.keras
IMAGE_CLASSES_PATH=data/image/class_indices.json
IMAGE_MANIFEST_PATH=data/image/index_manifest.json
```

The **PostgreSQL user, database and password must match the source volume**. Changing `POSTGRES_PASSWORD` on an already initialized restored volume does not change that database user's password. The Neo4j credentials must likewise match the exported graph. Obtain those values privately from the teammate who exported the data. URL-encode special characters in the password portion of `DATABASE_URL` (for example `@` becomes `%40`). Keep `.env` out of chat, screenshots, logs and Git.

`frontend/.env.local` normally keeps `BACKEND_URL=http://127.0.0.1:8000`. Set `BACKEND_API_KEY` to the same value as root `API_KEY` **only if** you enabled a shared API key; otherwise leave both empty for the explicit local development bypass. The browser never receives the server-side key.

### 4. Restore the volumes, image assets, and `neo4j-dev`

Run the purpose-built script **once on a fresh Docker setup**:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restore_team_handoff.ps1
```

It verifies every SHA-256 checksum and archive before touching Docker. It then loads images, creates the three named volumes, extracts their contents, restores `data/image/`, creates the `neo4j-dev` container, and starts Neo4j/PostgreSQL/Qdrant. It refuses to overwrite an existing container or volume. It never clears data implicitly.

To check the transferred archives without needing `.env` or modifying Docker, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restore_team_handoff.ps1 -VerifyOnly`.

If an earlier failed setup already created any of those three containers/volumes, first decide whether **all their data is disposable**. Back up anything you need. Only then run the explicit reset option:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restore_team_handoff.ps1 -ResetTargetVolumes
```

That switch removes **only** `neo4j-dev`, `impark-major-project-postgres-1`, `impark-major-project-qdrant-1` and their three named volumes, then restores from the verified handoff. It is destructive to data currently in those targets. Do not use it on an active project copy with new chat history.

If you want to inspect the restored files before starting databases, pass `-SkipStart`; then later run `docker start neo4j-dev` and `docker compose --profile stores up -d postgres qdrant`.

### 5. Install the local chat model and launch

```powershell
ollama pull gemma4:e4b
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo.ps1
```

The demo launcher checks `.env`, required dependencies and database readiness, then starts the backend on `http://127.0.0.1:8000` and Next.js on `http://127.0.0.1:3000`. It warms the **active** `AGENT_MAIN_MODEL`. Open the frontend and try plant-name autocomplete, select one plant, then ask a follow-up. The first local model response may still take time on limited VRAM.

Use `-Restart` after code or environment changes. Use `-DevFrontend` for hot reload. `-SkipDocker` is for already-running or external stores; `-SkipWarmup` skips the final live checks, not service startup. The launcher does not create or restore missing database volumes.

### 6. Verify the restored data

```powershell
docker ps --format 'table {{.Names}}\t{{.Status}}'
.\.venv\Scripts\python.exe -m backend.database.neo4j health
.\.venv\Scripts\python.exe -m backend.database.neo4j inspect
.\.venv\Scripts\python.exe -m backend.database.search_admin health
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/postgres
Invoke-RestMethod http://127.0.0.1:8000/health/qdrant
```

The source snapshot was previously reported as 4,075 graph nodes and 11,697 relationships. Compare the **actual** `inspect` output to the exported source; the container being “running” does not prove the graph was restored correctly. PostgreSQL and Qdrant must represent the same name-search generation. On an intact cold handoff, **do not run `sync` just because it is a first setup**: the projection is already restored. `sync` explicitly rebuilds it and is appropriate only if it is missing/stale or the underlying graph changed. The same applies to the supplied image index.

## B. No handoff archives: build local stores from source data

This path requires a separately populated Neo4j graph and the original image model/dataset. It cannot synthesize the research data. Set `.env` as above, start/create a local `neo4j-dev` yourself (or use a configured Aura instance with `-SkipDocker`), then:

```powershell
docker compose --profile stores up -d postgres qdrant
.\.venv\Scripts\python.exe -m backend.database.search_admin migrate
.\.venv\Scripts\python.exe -m backend.database.search_admin sync
```

`migrate` applies numbered PostgreSQL migrations, creates LangGraph checkpoint tables and provisions Qdrant. `sync` projects the configured Neo4j plant names/aliases into PostgreSQL and Qdrant. Neither runs at web startup. If you have the supplied image model/dataset but no image Qdrant collection, explicitly extract/build it:

```powershell
.\.venv\Scripts\python.exe -m backend.agents.image.admin extract --dataset data/image/dataset --model data/image/xception_model.keras --classes data/image/class_indices.json --output data/image/features.npz
.\.venv\Scripts\python.exe -m backend.agents.image.build_index --cache data/image/features.npz --manifest data/image/index_manifest.json
```

Only set `IMAGE_ENABLED=true` after the model, class map, manifest and collection exist. The supported model covers its 40 leaf classes, not arbitrary plants or plant parts. A restored volume should not normally need these rebuild steps.

## Common failures and what to do

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `Docker Desktop Linux engine is unavailable` | Docker Desktop is closed or using Windows containers. | Start Docker Desktop, switch to Linux containers, retry `docker version`. |
| `Volume ... already exists` during restore | A previous Compose/demo run initialized empty or different data. | Back up anything needed; run `-ResetTargetVolumes` only if all three target volumes are disposable. |
| `neo4j-dev is missing` from demo | The Neo4j volume alone is not a runnable container. | Run `restore_team_handoff.ps1`; it creates the container after restoring the volume. |
| Neo4j cannot bind 7474/7687 | Another Neo4j container, often the optional Compose `neo4j` service, already owns the ports. | Stop that other container; the handoff uses `neo4j-dev` and `neo4j_dev_data`. Do not start both Neo4j variants. |
| PostgreSQL or Neo4j authentication fails | `.env` has new/different credentials; restored volumes retain original users. | Obtain the source credentials securely; fix `.env` and `DATABASE_URL`. |
| Backend exits during startup | Store is unavailable, migration/search generation missing, image artifact missing or another backend holds the process lease. | Read `data/demo-backend.err.log`. For a genuinely fresh DB run explicit `migrate`/`sync`; for a restored DB first check mount names and credentials. |
| Frontend build/start fails | `npm ci` not run, wrong Node version, or port 3000 occupied. | Read `data/demo-frontend.err.log`; run `npm ci`; check port owner. |
| Warmup fails after servers start | Ollama not running/model not pulled, Qdrant unavailable, or API configuration mismatch. | Read the printed failed check; run `ollama list`, store health commands, then `demo.ps1 -Restart`. |
| Another service is on ports 3000/8000/7474/7687/15432/6333 | Port conflict. | Identify it and stop/reconfigure it. `-Restart` only stops recognized IMPARK listeners on 3000/8000. |
| Image capability unavailable | Image model, class map, manifest or Qdrant collection missing. | Restore `image-assets.tgz` or rebuild the image index; check `IMAGE_*` settings. |

`/health/llm` confirms configuration, not live generation quality. `scripts/demo_warmup.py` performs an actual small Ollama generation and search/health checks. The API is a **single-process demo**: startup obtains a PostgreSQL advisory lease, so stop another backend process before starting a second one. No startup operation seeds Neo4j, migrates databases, or copies development data to Aura.

For architectural ownership, see [architecture](../architecture/README.md); for all endpoints and session flow, see [API and frontend](../api-and-frontend/README.md). The export script is [scripts/export_team_handoff.ps1](../../scripts/export_team_handoff.ps1) and the restore script is [scripts/restore_team_handoff.ps1](../../scripts/restore_team_handoff.ps1).
