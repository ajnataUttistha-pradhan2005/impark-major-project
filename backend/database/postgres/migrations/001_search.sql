CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE IF NOT EXISTS search_generation (
    generation uuid PRIMARY KEY,
    imported_at timestamptz NOT NULL DEFAULT now(),
    embedding_model text NOT NULL,
    plant_count integer NOT NULL,
    name_count integer NOT NULL,
    status text NOT NULL CHECK (status IN ('staging','active','retired'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_search_generation
ON search_generation(status) WHERE status = 'active';
CREATE TABLE IF NOT EXISTS search_plant (
    generation uuid NOT NULL REFERENCES search_generation(generation),
    plant_id uuid NOT NULL,
    plant_name text NOT NULL,
    source_key text NOT NULL,
    PRIMARY KEY(generation, plant_id)
);
CREATE TABLE IF NOT EXISTS search_name (
    generation uuid NOT NULL,
    name_id uuid NOT NULL,
    plant_id uuid NOT NULL,
    name text NOT NULL,
    normalized_name text NOT NULL,
    source_normalized_alias text,
    alias_type text,
    language text,
    source_key text NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', normalized_name)) STORED,
    PRIMARY KEY(generation, name_id),
    FOREIGN KEY(generation,plant_id) REFERENCES search_plant(generation,plant_id)
);
CREATE INDEX IF NOT EXISTS search_name_exact ON search_name(generation,normalized_name);
CREATE INDEX IF NOT EXISTS search_name_prefix ON search_name(normalized_name text_pattern_ops);
CREATE INDEX IF NOT EXISTS search_name_fts ON search_name USING gin(search_vector);
CREATE INDEX IF NOT EXISTS search_name_trigram ON search_name USING gin(normalized_name gin_trgm_ops);
CREATE TABLE IF NOT EXISTS app_session (
    session_id uuid PRIMARY KEY,
    state jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app_turn (
    run_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES app_session(session_id),
    state jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_turn_session ON app_turn(session_id,created_at);
CREATE TABLE IF NOT EXISTS domain_trace (
    event_id uuid PRIMARY KEY,
    session_id uuid,
    run_id uuid,
    event_type text NOT NULL,
    event jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trace_run ON domain_trace(run_id,created_at);
CREATE TABLE IF NOT EXISTS text_evaluation (
    evaluation_id uuid PRIMARY KEY,
    report jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
