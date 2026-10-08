# Text / Entity ownership

Normalization is implemented; `TextAgent` delegates candidate search to an injected provider.
Without a provider it returns a marked placeholder. Implement extraction, ranking, aliases,
coreference and reassessment through the existing ports and small owning modules.

Cascade: exact ID/name/alias -> PostgreSQL FTS -> pg_trgm/RapidFuzz -> semantic search -> bounded
disambiguation among existing candidates. Intent interpretation and goal planning are still TODO;
the API intentionally does not fabricate graph intents. Provider results need provenance.
