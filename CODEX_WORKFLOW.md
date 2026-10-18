# Contributor workflow

Read [AGENTS.md](AGENTS.md), [current architecture](docs/architecture/README.md), [file map](docs/repository-map/README.md), and the relevant API/setup/testing guide before edits. Inspect call sites and tests, make the smallest coherent change, preserve typed graph safety and one-plant scope, update exported contracts for API changes, and run targeted tests plus available lint/type checks. Document any new behavior and any inability to verify it. The former advice to preserve the custom deterministic harness was superseded when the project adopted DeepAgents.
