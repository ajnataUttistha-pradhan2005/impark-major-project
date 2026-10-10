CREATE TABLE IF NOT EXISTS search_entity (
    generation uuid NOT NULL REFERENCES search_generation(generation),
    entity_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('compound','therapeutic_use','target')),
    label text NOT NULL,
    normalized_label text NOT NULL,
    PRIMARY KEY(generation,kind,entity_id,label)
);
CREATE INDEX IF NOT EXISTS entity_exact ON search_entity(generation,normalized_label);
CREATE INDEX IF NOT EXISTS entity_trigram ON search_entity USING gin(normalized_label gin_trgm_ops);
