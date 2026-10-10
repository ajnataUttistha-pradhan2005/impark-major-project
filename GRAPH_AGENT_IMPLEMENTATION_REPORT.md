# Graph Agent implementation report — 2026-10-10

## Delivered

The scoped Graph Agent is implemented and wired into the existing application. It covers the
13 applicable Neo4j retrieval types, same-plant citation tracing, bounded results with explicit
limitations, missing-source observations, property conflicts, and safe error/retry handling.
The current single-plant policy deliberately rejects COMPARE_PLANTS and global reverse questions.
See GRAPH_AGENT_GUIDE.md for the precise coverage and remaining scope limits.

Discovery establishes and locks one plant; conversation reuses it. Text, image-provider outputs,
explicit selections, clarification and graph dispatch cannot silently switch plants. The initial
question survives candidate selection. All 17 actual graph part values are understood as scopes.
The API supplies a session notice; frontend rendering itself is a separate, unimplemented milestone.

## Validation

Final full run: **273 passed, 2 skipped**, zero failures (112.99 seconds).
The two skipped cases are explicitly opt-in Neo4j write/rollback tests; this run kept graph writes
disabled. Ruff lint and formatting pass (135 files); mypy passes (102 source files); pip check
reports no broken requirements. `git diff --check` passes. Machine-readable results are in
`data/evaluation/graph_agent_tests.xml`. Local graph inspection confirmed 4,075 nodes and 11,697
relationships. No knowledge-graph data/schema changes were made.

Coverage includes every retrieval template against the real schema, evidence paths and branched
relationships, scoped filters, stable citations and trace snapshots, invalid/injected inputs,
empty/oversized/truncated results, data conflicts, transient/permanent failures, original-question
clarification, same-session follow-ups, other-plant rejection and Text/Image provider boundaries.

Synthetic scenarios exercise failure/contradiction conditions. Live tests exercise Neo4j plus the
populated PostgreSQL/Qdrant catalog and the FastAPI/LangGraph application. These results do not
claim universal language accuracy, clinical validation, or a finished image model/frontend.

## Files changed for this task

- `backend/agents/graph/agent.py`, `retrieval.py`, `README.md`: provider integration, query coverage,
  bounded evidence/path construction, source quality, contradictions and failure mapping.
- `backend/database/neo4j/repository.py`: adapt the existing graph-provider contract to typed
  invocation input, objective IDs and citation history; no duplicate graph connection layer.
- `backend/agents/common/parts.py`: verified plant-part vocabulary and explicit normalized tokens.
- `backend/agents/text/agent.py`, `interpretation.py`, `README.md`: scoped intent/entity planning,
  evidence tracing, one-plant policy and full verified part vocabulary.
- `backend/contracts/agents.py`, `evidence.py`: scope/result metadata, path provenance and terminal
  gaps, preserving backward defaults.
- `backend/state/models.py`, `goals.py`: persistent plant lock, bounded citation history,
  unavailable objectives and SCOPE_REJECTED outcome.
- `backend/evidence/evaluator.py`, `context_builder.py`: evidence retention/limitations, conflict
  categories and deterministic response context.
- `backend/orchestrator/execution.py`, `orchestrator.py`, `policy.py`, `termination.py`,
  `clarification.py`: plant-scope enforcement, terminal gaps, safe recovery and graph tool traces.
- `backend/services/conversations.py`, `backend/api/schemas/chat.py`: selection guards, original
  question preservation and frontend-facing session notice.
- `backend/llm/grounded.py`: source URLs, trace-path display and scope-rejection response.
- `tests/graph/test_retrieval.py`, `test_live.py`: synthetic contract and real-schema coverage.
- `tests/text/test_graph_integration.py`, `test_agent.py`, `test_stores_live.py`: combined agent,
  harness, lifecycle, API and store validation; replace superseded plant-switch expectations.
- `AGENTS.md`, `INSTRUCTIONS.md`, `ARCHITECTURE.md`, `API.md`, `DECISIONS.md`, `TASKS.md`,
  `README.md`, `TEXT_ENTITY_GUIDE.md`, `HARNESS_GUIDE.md`, `frontend/README.md`: align the current
  session policy and integration documentation.
- `GRAPH_AGENT_GUIDE.md`, this report and the XML test report: implementation and validation record.

Earlier Neo4j/Text Agent/store/harness changes were already uncommitted when this task resumed;
they were preserved. No commit or push was performed.
