# Text / Entity ownership

TextAgent returns typed observations/failures and never mutates global state. Interpretation
extracts supported intents, part scopes and plant-scoped entity filters. Search implements
exact ID/name/alias, PostgreSQL FTS, trigram/RapidFuzz and optional semantic retrieval.
Normalization retains Indic marks; embedding inference runs off the event loop.
Candidate metadata carries provenance and match methods.

Coreference requires established context; explicit other plants are rejected once the session plant is locked. Ambiguous aliases,
spelling suggestions and semantic matches require confirmation. Unsupported intents and multiple
part scopes ask for clarification. Reassessment excludes weakened identities.
Decision-model fallback and its experimental artifacts have been removed. Without an injected provider, the
foundation still returns a marked placeholder. See the root TEXT_ENTITY_GUIDE.md and report.
