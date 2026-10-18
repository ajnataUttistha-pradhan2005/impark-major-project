# Setup, data stores, artifacts, and operations

Commands below run from the repository root in Windows PowerShell. They configure a **local development demo**; do not point import/migration commands at a production database without reviewing the destination. Source secrets belong in ignored `.env`/`frontend/.env.local`, never in documentation or committed code.

## Prerequisites and installation

Install Python 3.12+, Node.js/npm, Docker Desktop with Linux containers, and Ollama if using local models. Obtain a populated Neo4j copy separately; the application does not seed it. The repo does not bundle model weights or the full image dataset. From the root:

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

Set `NEO4J_ENABLED`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`; `TEXT_SEARCH_ENABLED`, `DATABASE_URL`, `QDRANT_URL`; PostgreSQL Compose credentials; and the `AGENT_*` model settings in `.env`. Set `BACKEND_URL` and, when required, `BACKEND_API_KEY` in `frontend/.env.local`. The same Neo4j client supports local Bolt or Aura URI via these values; `DATABASE_URL`/`QDRANT_URL` can similarly point to local or cloud services. Use TLS and provider credentials appropriate to the destination. `Settings` validates required combinations at startup. Do not copy real credentials from another teammate's `.env`.

`AGENT_MAIN_MODEL_PROVIDER`/`AGENT_MAIN_MODEL` choose the orchestrator model. `AGENT_TEXT_*`, `AGENT_IMAGE_*`, and `AGENT_GRAPH_*` override each specialist separately; blank values inherit main. Ollama uses `OLLAMA_BASE_URL`, `LLM_CONTEXT_TOKENS`, and `LLM_OUTPUT_TOKENS`; non-Ollama providers need the relevant LangChain package and environment credentials. Pull a locally configured model explicitly (for example `ollama pull gemma4:e4b`). `LLM_PROVIDER`, `LLM_RESPONSE_MODE`, and several older budget settings remain in `Settings` for older utilities/compatibility; they do not select the active DeepAgents main answer path. The active runtime enforces its own graph-call and recursion/time limits. Do not assume the old `plant_context` switch changes DeepAgents behavior.

## Local stores and explicit preparation

`docker-compose.yml` has a `stores` profile for PostgreSQL 17, Qdrant 1.13.6, Neo4j 2026.09.0, and Redis 7. The demo launcher normally starts **PostgreSQL and Qdrant** via Compose and expects the separately populated `neo4j-dev` container. Avoid running both Neo4j containers on the same host ports. The optional backend Compose service is separate from the supported Windows-host demo path.

```powershell
docker compose --profile stores up -d postgres qdrant
docker start neo4j-dev
.\.venv\Scripts\python.exe -m backend.database.search_admin migrate
.\.venv\Scripts\python.exe -m backend.database.search_admin sync
.\.venv\Scripts\python.exe -m backend.database.search_admin health
```

`migrate` applies numbered PostgreSQL SQL migrations, sets up LangGraph checkpoint tables, and provisions Qdrant search collections. `sync` reads names/aliases from the configured Neo4j graph and rebuilds the PostgreSQL/Qdrant name projection with a generation identifier. Neither command runs at web startup. The migrations cover search, entity catalog, chat API, and reference notes (`001`–`004`). The graph repository reads typed paths from the actual Neo4j labels/relationships; do not mutate or clear the research graph as part of setup. Optional `python -m backend.evidence.reference_import --limit 500` imports verified linked MeSH descriptions into PostgreSQL; this is an explicit network/data operation and definitions are contextual, not plant-specific treatment proof.

The graph model used by code includes `PlantDetails`, `PlantAlias`, `PlantPart`, `Phytochemicals`, `TherapeuticUse`, `Bioactivity`, `Protein_Target`, and `Document`; the known relationship vocabulary is `HAS_ALIAS`, `HAS_PART`, `CONTAINS`, `USED_FOR`, `HAS_BIOACTIVITY`, `MEASURED_ON`, and `REPORTED_IN`. See `backend/database/neo4j/queries.py` and `backend/agents/graph/retrieval.py` for the **exact** paths and projected properties. The connection interface itself is environment-neutral; feature availability still depends on the destination graph data/schema.

The text embedding model defaults to `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` with 384 dimensions; its cache is `data/model-cache/`. Qdrant text and image collections must have different names (`plant_names_v1`, `plant_images_v1` by default). The image path uses `data/image/xception_model.keras`, `class_indices.json`, `index_manifest.json`, and an indexed leaf-image dataset. Build the features/index explicitly before enabling the image capability:

```powershell
.\.venv\Scripts\python.exe -m backend.agents.image.admin extract --dataset data/image/dataset --model data/image/xception_model.keras --classes data/image/class_indices.json --output data/image/features.npz
.\.venv\Scripts\python.exe -m backend.agents.image.build_index --cache data/image/features.npz --manifest data/image/index_manifest.json
```

Then set `IMAGE_ENABLED=true` and verify its artifact paths/collection. Image inference covers the model's supported 40 leaf classes, not unrestricted species identification or a validated plant-part/non-plant classifier. The dataset, weights, and extraction cache are intentionally ignored by Git; the class map and manifest are versioned. `training/image/train_model.py` is a training recipe, not a startup prerequisite.

## Run and observe

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1
# Or, in two terminals:
.\.venv\Scripts\python.exe -m backend
Push-Location frontend; npm run dev
```

The script exposes `-Restart`, `-SkipDocker`, `-SkipWarmup`, and `-DevFrontend`; inspect its help/source before using switches in a different environment. It starts/checks local services and writes demo logs under `data/`. Check `/health` and store-specific health routes, then the UI at port 3000 and `/docs` at port 8000. `/health/llm` only confirms a model is configured, not that a generation succeeded or is scientifically accurate. The API runs as a single backend process: lifespan obtains a PostgreSQL advisory lease and rejects another process using the same demo database. Do not deploy multiple workers without redesigning run coordination and checkpoint/event ownership.

## Cold teammate handoff

`scripts/export_team_handoff.ps1` is the repository's explicit cold-export tool. It stops the recognized database containers for a consistent volume snapshot, saves Docker images and image assets, computes checksums, and restarts services. Read and run that script in the local environment rather than assuming archive names/paths from an older note. The intended output is the ignored `backups/team-handoff/` folder, transferred privately alongside the matching Git commit. Do not commit database volumes, research data, model weights, or credentials. The receiver should verify the provided checksums, load saved images with `docker image load`, restore each archive to the named Docker volume **before starting containers**, copy image assets into `data/image/`, set their own `.env`, then run explicit migration/health checks. Volume names depend on the Compose project name and the separately managed Neo4j container; inspect the export manifest/script to match source and destination exactly. PostgreSQL and Qdrant snapshots must correspond to the same search generation; otherwise rerun `sync` on the receiver. Ollama's model cache is not one of these Docker volumes, so the receiver pulls its model separately.

For the current exporter, run `powershell -ExecutionPolicy Bypass -File .\scripts\export_team_handoff.ps1` only on the source machine after checking its exact container/volume names. It expects running `neo4j-dev`, `impark-major-project-postgres-1`, and `impark-major-project-qdrant-1`; volumes `neo4j_dev_data`, `impark-major-project_postgres-data`, `impark-major-project_qdrant-data`; and the model/dataset/features under `data/image/`. It creates `neo4j-data.tgz`, `postgres-data.tgz`, `qdrant-data.tgz`, `database-images.tar`, `image-assets.tgz`, and `SHA256.txt` in the chosen destination. It refuses to overwrite an existing archive.

On the receiver, from the matching checkout with the transferred folder at `backups/team-handoff`, restore **before** starting any database containers. Confirm target volumes are new/empty; the following overlays files and is not a merge strategy for preexisting data:

```powershell
$handoff = (Resolve-Path 'backups/team-handoff').Path
Get-Content (Join-Path $handoff 'SHA256.txt') | ForEach-Object {
  $expected, $name = $_ -split '\s+', 2
  $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $handoff $name.Trim())).Hash
  if ($actual -ne $expected) { throw "Checksum mismatch: $name" }
}
docker image load --input (Join-Path $handoff 'database-images.tar')
docker volume create neo4j_dev_data
docker volume create impark-major-project_postgres-data
docker volume create impark-major-project_qdrant-data
$items = @(
  @{Volume='neo4j_dev_data'; Archive='neo4j-data.tgz'},
  @{Volume='impark-major-project_postgres-data'; Archive='postgres-data.tgz'},
  @{Volume='impark-major-project_qdrant-data'; Archive='qdrant-data.tgz'}
)
foreach ($item in $items) {
  docker run --rm --mount "type=volume,source=$($item.Volume),target=/target" --mount "type=bind,source=$handoff,target=/backup,readonly" alpine:3.20 tar -C /target -xzf "/backup/$($item.Archive)"
  if ($LASTEXITCODE -ne 0) { throw "Restore failed: $($item.Volume)" }
}
tar.exe -xzf (Join-Path $handoff 'image-assets.tgz') -C .
```

Then create the recipient's own `.env`, use `COMPOSE_PROJECT_NAME=impark-major-project`, start the matching containers, and run the health commands above. A separate `neo4j-dev` container must be created/mounted to `neo4j_dev_data` with correct auth/ports if the recipient does not already have one; the provided Compose `neo4j` service uses a different volume name and container identity. Check the graph contents and search generation after restore rather than inferring correctness from container startup. If the source and recipient paths, container versions, or volume names differ, adapt those **explicitly** before extraction.

## Data and operational ownership

| Store | Owns | Setup/recovery consequence |
| --- | --- | --- |
| PostgreSQL | Sessions, turns, chat messages/images, operations/events, search catalog, reference notes, traces, LangGraph checkpoints | Migrate explicitly; persist/restore for chat history and resumes. |
| Neo4j | Curated medicinal-plant graph | Use an already populated local/Aura graph; application reads through typed queries. |
| Qdrant | Text-name and image-reference vectors in distinct collections | Provision/index explicitly; align text generation with PostgreSQL or resync. |
| Ollama/provider | Four configured chat-model roles | Install/pull/configure outside the database backup; latency depends on hardware/provider. |
| Redis | Optional adapter/service | Not opened in current `create_app()` and not required for the demo flow. |

The health routes are component probes, not end-to-end quality evaluations. See [testing and limitations](../testing-and-limitations/README.md) before claiming live data or model coverage.
