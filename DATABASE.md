# Data stores and schema

PostgreSQL owns durable sessions, turns, chat messages/images, operations/events, name-search projection, reference notes, trace/evaluation data and LangGraph checkpoints. Neo4j owns the curated graph; Qdrant owns separate text-name and image-reference vector collections. Redis has an optional adapter but is not opened by current app startup. Migration, graph projection and image indexing are explicit administration tasks, never web-startup side effects.

See [architecture and migration tables](docs/architecture/README.md#data-and-evidence-boundaries), [setup and recovery](docs/setup-and-operations/README.md), and the actual `backend/database/postgres/migrations/` and `backend/database/neo4j/queries.py` for exact schema/query details.
