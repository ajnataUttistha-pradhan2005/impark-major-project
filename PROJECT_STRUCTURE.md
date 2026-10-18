# Repository structure

The [current file map](docs/repository-map/README.md) lists the purpose of every major folder and relevant file in the inspected checkout. The active agent implementation lives in `backend/orchestrator/deepagents/`; the specialists remain in `backend/agents/{text,image,graph}/`; versioned HTTP contracts live in `backend/api/` and are exposed to the Next.js frontend. The historical target-tree plan has been superseded by this implemented layout.
