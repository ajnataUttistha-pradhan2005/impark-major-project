ALTER TABLE app_session ADD COLUMN IF NOT EXISTS title text NOT NULL DEFAULT 'New chat';
ALTER TABLE app_session ADD COLUMN IF NOT EXISTS archived boolean NOT NULL DEFAULT false;
ALTER TABLE app_session ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS app_session_list ON app_session(archived,updated_at DESC,session_id);
CREATE TABLE IF NOT EXISTS api_operation (
    operation_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES app_session(session_id) ON DELETE CASCADE,
    request_hash text NOT NULL,
    run_id uuid,
    request jsonb NOT NULL,
    status text NOT NULL CHECK(status IN ('accepted','running','interrupted','complete','cancelled','failed')),
    result jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS api_one_active_operation ON api_operation(session_id)
WHERE status IN ('accepted','running','interrupted');
CREATE TABLE IF NOT EXISTS chat_message (
    message_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES app_session(session_id) ON DELETE CASCADE,
    operation_id uuid NOT NULL REFERENCES api_operation(operation_id) ON DELETE CASCADE,
    role text NOT NULL CHECK(role IN ('user','assistant')),
    content text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'pending',
    data jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(operation_id,role)
);
CREATE INDEX IF NOT EXISTS chat_message_page ON chat_message(session_id,created_at,message_id);
CREATE TABLE IF NOT EXISTS api_event (
    operation_id uuid NOT NULL REFERENCES api_operation(operation_id) ON DELETE CASCADE,
    sequence integer NOT NULL CHECK(sequence > 0),
    event jsonb NOT NULL,
    PRIMARY KEY(operation_id,sequence)
);
CREATE TABLE IF NOT EXISTS chat_image (
    image_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES app_session(session_id) ON DELETE CASCADE,
    metadata jsonb NOT NULL,
    content bytea NOT NULL CHECK(octet_length(content) <= 5242880),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_image_session ON chat_image(session_id);

ALTER TABLE domain_trace ADD CONSTRAINT domain_trace_session_fk
FOREIGN KEY(session_id) REFERENCES app_session(session_id) ON DELETE CASCADE NOT VALID;
