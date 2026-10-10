# Graph Agent ownership

`GraphAgent.execute(GraphAgentInput)` returns typed Observation/Failure. `PlantGraphRetrieval`
implements the existing GraphRepository protocol, accepting a typed query, requested objective IDs,
gaps and recent same-plant evidence. No agent may mutate harness state or choose actions.

Thirteen static Neo4j query templates cover the verified graph; TRACE_EVIDENCE returns a bounded
session citation snapshot. Cross-plant comparisons are explicitly rejected. Every read anchors the
active plant, parameterizes values and enforces a timeout and result limit. Actual nodes, directed
relationship endpoints, URLs and stable citation IDs provide provenance. Evidence classes remain
unknown unless supported by future verified data. Empty results are gaps, never negative proof.

The main application injects the real adapter when Neo4j and search stores are enabled. The
unconfigured foundation still returns a marked placeholder; it never fabricates evidence.
See [GRAPH_AGENT_GUIDE.md](../../../GRAPH_AGENT_GUIDE.md) for usage, scope, validation and limitations.
