# Current implementation specification

IMPARK is a single-user educational demo with discovery, one locked plant per chat, and context-aware conversation. One DeepAgents main orchestrator delegates to exactly three specialist subagents; an outer LangGraph supplies checkpointed clarification. The main answer can combine cited graph facts with clearly general pretrained explanation. Do not infer treatment efficacy or invent plant-specific findings. The old deterministic scoring/action-loop specification is superseded.

The implemented architecture and boundaries are documented in [docs/architecture](docs/architecture/README.md), the complete [API contract](docs/api-and-frontend/README.md), [database and run setup](docs/setup-and-operations/README.md), and [testing limits](docs/testing-and-limitations/README.md). Root [AGENTS.md](AGENTS.md) defines current repository editing rules. Consult code for the final authority on exact behavior.
