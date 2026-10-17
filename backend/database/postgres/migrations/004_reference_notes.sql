CREATE TABLE IF NOT EXISTS reference_note (
    source text NOT NULL CHECK (source IN ('mesh')),
    external_id text NOT NULL,
    label text NOT NULL,
    description text NOT NULL,
    source_url text NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, external_id),
    CHECK (length(external_id) <= 64 AND length(label) <= 200
           AND length(description) <= 1200 AND length(source_url) <= 300)
);
