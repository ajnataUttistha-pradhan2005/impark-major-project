-- ==============================================================================
-- IMPARK Database Initialization Script
-- Initializes both Arize Phoenix tracing and Evaluator databases
-- ==============================================================================

SELECT 'CREATE DATABASE phoenix' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'phoenix')\gexec
SELECT 'CREATE DATABASE eval_db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'eval_db')\gexec
