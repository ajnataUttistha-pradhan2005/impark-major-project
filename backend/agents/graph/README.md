# Graph Agent handoff

Implement `GraphAgent.execute(GraphAgentInput) -> Observation | Failure` without changing harness
state. `backend/contracts/agents.py` owns all 15 query types, typed parameters, read-only flag,
result limit and timeout. Implement controlled templates behind `GraphRepository`, parameterize
values, and use a read-only Neo4j principal. No raw Cypher input, final prose or action selection.

Current agent returns `GraphAgentOutput(placeholder=True)` with no evidence. Replace this only with
real provider results and provenance. Empty retrieval is a gap, not proof that a claim is false.
Physical schema, ingestion and provider integration remain TODO (R-005/R-010).
