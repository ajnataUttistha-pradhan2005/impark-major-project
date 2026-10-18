# Architecture

The current application has one DeepAgents main orchestrator and three specialists (Text/Entity, Image Understanding, Knowledge Graph), behind `ConversationService` and an outer LangGraph checkpoint/clarification graph. The former custom action-scoring harness is retired. The active composition root is `backend/main.py`.

Read the [implemented architecture](docs/architecture/README.md) for component, agent, state, evidence, data-flow and sequence diagrams; the [file map](docs/repository-map/README.md) for ownership; and the [runtime guide](backend/orchestrator/deepagents/README.md) for tool and model behavior. These references reflect inspected code, not the earlier proposal.
