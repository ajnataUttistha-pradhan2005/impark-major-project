# Coding standards

Use Python 3.12+ typing, Pydantic v2 external contracts, async I/O, explicit dependency lifecycle and narrow exception handling. Keep FastAPI routes transport-only, session/run policies in services, agent delegation in `backend/orchestrator/deepagents/`, and store queries in repositories. Keep Neo4j retrieval typed, parameterized, bounded and read-only. Do not block the event loop with model/image work or log secrets. Use correlation IDs and preserve provenance/evidence classes. Add regression tests for behavior changes; regenerate frontend contracts when API schemas change. Avoid unrelated refactors and undocumented architecture changes.

The [current file map](docs/repository-map/README.md) and [architecture](docs/architecture/README.md) show module boundaries; [testing](docs/testing-and-limitations/README.md) gives validation commands.
