# Development workflow

Use [setup and operations](docs/setup-and-operations/README.md) for local/cloud connection values, Python/Node/Docker/Ollama setup, explicit migrations and indexing, demo launch, and teammate cold handoff. Use [testing and limitations](docs/testing-and-limitations/README.md) for verification commands and live-test preconditions. Edit the current runtime under `backend/orchestrator/deepagents/`; inspect all route/service call sites before changing public contracts. Do not run migrations, seed, or clear stores automatically at startup.
