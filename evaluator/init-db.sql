-- ==============================================================================
-- IMPARK Database Initialization Script
-- Initializes Arize Phoenix tracing and evaluation storage
-- ==============================================================================

SELECT 'CREATE DATABASE phoenix' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'phoenix')\gexec

\connect phoenix

CREATE TABLE IF NOT EXISTS agent_evaluations (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64),
    span_id VARCHAR(64),
    user_input TEXT,
    agent_output TEXT,
    retrieved_context TEXT,
    graph_retrieval_time_ms DOUBLE PRECISION,
    tool_selection_accuracy DOUBLE PRECISION,
    groundedness DOUBLE PRECISION,
    hallucination_rate DOUBLE PRECISION,
    judge_reasoning TEXT,
    raw_payload JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_evals_trace ON agent_evaluations(trace_id);
