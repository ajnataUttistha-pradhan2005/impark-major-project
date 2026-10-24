# ==============================================================================
# IMPARK Pipeline Verification & End-to-End Simulation Script
# Tests Flow 1 (Live Interactive Chat) & Flow 2 (Golden Dataset Benchmark)
# ==============================================================================

import json
import logging
import os
import sys
import time
import uuid

# Add evaluator directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from local_tracer import LocalRedisTracer
from redis_evaluator import (
    evaluate_all_metrics,
    extract_fields,
    split_into_sentences,
    init_models,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("impark.evaluator.test")


def test_sentence_splitter():
    """Verifies that context is cleanly chunked without losing sentence structure."""
    text = (
        "Withania somnifera is an adaptogenic herb. It contains withanolides and withaferin A. "
        "Studies demonstrate significant anti-inflammatory and neuroprotective effects! "
        "Is it toxic? Preclinical trials show high safety margins."
    )
    sentences = split_into_sentences(text)
    assert len(sentences) == 5, f"Expected 5 sentences, got {len(sentences)}"
    assert "Withania somnifera is an adaptogenic herb." in sentences
    logger.info("[PASS] test_sentence_splitter passed (5 sentences extracted cleanly).")


def simulate_flow_1_interactive_chat():
    """
    Flow 1 Simulation: Production Interactive User Chat Mode.
    - Zero ground truth data (ground_truth=None, expected_agent=None)
    - Verifies that tool_accuracy, answer_correctness, and context_recall default cleanly to NULL (None).
    - Verifies that retrieval_time_ms, groundedness_score, and hallucination_prob are computed.
    """
    logger.info("\n--- [Flow 1] Simulating Production Interactive User Chat ---")

    tracer = LocalRedisTracer(retrieval_node_name="knowledge_graph")
    tracer.reset()

    # Simulate node execution and latencies
    tracer.record_node("text_entity", 14.2)
    tracer.record_node("knowledge_graph", 48.7)
    tracer.add_context(
        "Ocimum tenuiflorum (Tulsi) leaves contain essential oils rich in eugenol (70%), "
        "caryophyllene, and ursolic acid. Eugenol inhibits COX-2 enzymes imparting anti-inflammatory action."
    )

    user_query = "What active phytochemicals are present in Tulsi and what are their actions?"
    agent_answer = (
        "Tulsi (Ocimum tenuiflorum) contains substantial amounts of eugenol, caryophyllene, and "
        "ursolic acid. Eugenol provides anti-inflammatory effects by inhibiting COX-2 enzymes."
    )

    # In production live chats, no ground truth or expected agent exists
    payload = tracer.publish_run(
        user_input=user_query,
        agent_output=agent_answer,
        expected_agent=None,
        ground_truth=None,
        extra_metadata={"session_id": str(uuid.uuid4()), "chat_mode": "interactive"},
    )

    # Verify payload format
    assert payload["expected_agent"] is None
    assert payload["ground_truth"] is None
    assert payload["retrieval_time_ms"] == 48.7
    assert len(payload["trajectory"]) == 2

    # Run evaluation
    fields = extract_fields(payload)
    scores = evaluate_all_metrics(fields)

    logger.info("Flow 1 Output Scores: %s", json.dumps(scores, indent=2))

    # Assertions for Flow 1
    assert scores["retrieval_time_ms"] == 48.7, "Retrieval latency should match monotonic timing."
    assert scores["tool_accuracy"] is None, "Tool accuracy MUST be None when expected_agent is None."
    assert scores["answer_correctness"] is None, "Answer correctness MUST be None when ground_truth is None."
    assert scores["context_recall"] is None, "Context recall MUST be None when ground_truth is None."
    assert scores["groundedness"] >= 0.0 and scores["groundedness"] <= 1.0, "Groundedness must be in [0, 1]."
    assert scores["hallucination_prob"] >= 0.0 and scores["hallucination_prob"] <= 1.0
    assert scores["is_hallucinated"] in (0, 1)

    logger.info("[PASS] Flow 1 Simulation Verified Successfully: Benchmark KPIs preserved from corruption.")
    return payload, scores


def simulate_flow_2_golden_benchmark():
    """
    Flow 2 Simulation: Offline Automated Benchmark Flow (Golden Dataset Item).
    - Supplies expected_agent and ground_truth.
    - Unlocks and evaluates all 6 core metrics.
    """
    logger.info("\n--- [Flow 2] Simulating Golden Dataset Offline Benchmark ---")

    tracer = LocalRedisTracer(retrieval_node_name="knowledge_graph")
    tracer.reset()

    tracer.record_node("text_entity", 12.1)
    tracer.record_node("knowledge_graph", 62.4)
    tracer.add_context(
        "Withania somnifera root extracts contain withanolides (notably withaferin A and withanolide D), "
        "alkaloids, and sitoindosides. Pharmacological actions include adaptogenic, GABA-mimetic neuroprotection, "
        "and immunostimulatory properties."
    )

    user_query = "What are the therapeutic constituents and biological actions of Withania somnifera?"
    agent_answer = (
        "Withania somnifera contains key withanolides including withaferin A, providing adaptogenic, "
        "immunostimulatory, and neuroprotective properties."
    )
    expected_agent = "knowledge_graph"
    ground_truth = (
        "Withania somnifera (Ashwagandha) is rich in withanolides such as withaferin A and withanolide D, "
        "which confer adaptogenic, neuroprotective, and immunomodulatory biological actions."
    )

    payload = tracer.publish_run(
        user_input=user_query,
        agent_output=agent_answer,
        expected_agent=expected_agent,
        ground_truth=ground_truth,
        extra_metadata={"benchmark_id": "golden_case_042", "eval_mode": "golden_dataset"},
    )

    # Verify payload format
    assert payload["expected_agent"] == expected_agent
    assert payload["ground_truth"] == ground_truth
    assert payload["retrieval_time_ms"] == 62.4

    fields = extract_fields(payload)
    scores = evaluate_all_metrics(fields)

    logger.info("Flow 2 Output Scores: %s", json.dumps(scores, indent=2))

    # Assertions for Flow 2 (All 6 metrics must be evaluated)
    assert scores["retrieval_time_ms"] == 62.4
    assert scores["tool_accuracy"] == 1.0, f"Expected tool_accuracy 1.0, got {scores['tool_accuracy']}"
    assert scores["groundedness"] is not None and scores["groundedness"] > 0.0
    assert scores["hallucination_prob"] is not None
    assert scores["is_hallucinated"] == 0, "Consistent evidence must not be flagged as hallucinated."
    assert scores["answer_correctness"] is not None, "Answer correctness must be populated."
    assert scores["answer_correctness"] > 0.4, "High semantic match should yield solid correctness."
    assert scores["context_recall"] is not None, "Context recall must be populated."
    assert scores["context_recall"] > 0.4, "Retrieved context contains ground truth entities."

    logger.info("[PASS] Flow 2 Simulation Verified Successfully: All 6 metrics evaluated with high precision.")
    return payload, scores


def test_live_docker_integration():
    """
    Tests live communication with Redis and PostgreSQL.
    - If containers are running, validates end-to-end writing/reading from Redis stream
      and inserting/querying PostgreSQL table 'agent_evaluations'.
    - If containers are offline and REQUIRE_LIVE_INFRA=1 is set, fails explicitly.
    - If containers are offline and REQUIRE_LIVE_INFRA is not set, notes skip cleanly.
    - NEVER masks database connection errors or authentications failures.
    """
    logger.info("\n--- Testing Live Infrastructure Connectivity (Redis & Postgres) ---")
    require_live = os.getenv("REQUIRE_LIVE_INFRA", "false").lower() in ("true", "1", "yes")

    redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    pg_host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    pg_port = int(os.getenv("EVAL_POSTGRES_PORT", os.getenv("POSTGRES_PORT", "5433")))
    pg_db = os.getenv("POSTGRES_DB", "eval_db")
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "password")

    try:
        import redis
    except ImportError:
        logger.error("[FAIL] 'redis' package is not installed. Please run: pip install redis")
        if require_live:
            raise AssertionError("Package 'redis' is missing.")
        return

    try:
        try:
            import psycopg2
            from psycopg2.extras import Json
        except ImportError:
            import psycopg as psycopg2  # type: ignore
            from psycopg.types.json import Jsonb as Json  # type: ignore
    except ImportError:
        logger.error("[FAIL] Neither 'psycopg2' nor 'psycopg' is installed. Please run: pip install psycopg2-binary")
        if require_live:
            raise AssertionError("PostgreSQL database client library is missing.")
        return

    # 1. Test Redis connectivity
    try:
        retry_strategy = None
        try:
            from redis.retry import Retry
            from redis.backoff import NoBackoff
            retry_strategy = Retry(NoBackoff(), 0)
        except ImportError:
            pass

        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            socket_timeout=0.2,
            socket_connect_timeout=0.2,
            retry=retry_strategy,
            decode_responses=True,
        )
        r.ping()
        logger.info("[PASS] Live Redis container is ONLINE at %s:%s.", redis_host, redis_port)
    except Exception as exc:
        if require_live:
            logger.error("[FAIL] Live Redis container is unreachable at %s:%s: %s", redis_host, redis_port, exc)
            raise AssertionError(f"Redis connection failed: {exc}")
        else:
            logger.info("[INFO] Live Redis not detected at %s:%s (%s). Skipping live infrastructure check.", redis_host, redis_port, exc)
            return

    # 2. Test PostgreSQL connectivity (since Redis is online, infrastructure is running)
    try:
        conn = psycopg2.connect(
            dbname=pg_db,
            user=pg_user,
            password=pg_pass,
            host=pg_host,
            port=pg_port,
            connect_timeout=5,
        )
        conn.autocommit = True
        logger.info("[PASS] Live PostgreSQL container is ONLINE at %s:%s (db=%s).", pg_host, pg_port, pg_db)
    except Exception as exc:
        logger.error(
            "[FAIL] PostgreSQL connection failed at %s:%s (db=%s, user=%s): %s",
            pg_host,
            pg_port,
            pg_db,
            pg_user,
            exc,
        )
        if pg_port == 5432 and "password authentication failed" in str(exc).lower():
            logger.error(
                "[DIAGNOSTIC] A native Windows PostgreSQL service is likely bound to port 5432. "
                "Ensure docker-compose.yml maps PostgreSQL to port 5433 ('5433:5432') and "
                "set EVAL_POSTGRES_PORT=5433 or run deploy_windows.ps1."
            )
        raise AssertionError(f"PostgreSQL connection failed: {exc}")

    # 3. Ensure target schema / table exists
    try:
        from redis_evaluator import init_database_schema
        init_database_schema(conn)
        logger.info("[PASS] Verified table 'agent_evaluations' schema and GIN index exist.")
    except Exception as exc:
        logger.error("[FAIL] Failed to initialize/verify database schema: %s", exc)
        conn.close()
        raise AssertionError(f"Database schema initialization failed: {exc}")

    # 4. Test writing to Redis Stream 'agent-logs'
    test_payload = {
        "trace_id": str(uuid.uuid4()),
        "user_input": "Integration Test Query",
        "retrieved_context": "Ashwagandha has withanolides.",
        "agent_output": "Ashwagandha contains withanolides.",
        "trajectory": ["knowledge_graph"],
        "expected_agent": "knowledge_graph",
        "ground_truth": "Ashwagandha contains withanolides.",
        "retrieval_time_ms": 25.5,
    }

    try:
        msg_id = r.xadd("agent-logs", {"payload": json.dumps(test_payload)})
        logger.info("[PASS] Successfully wrote live trace %s to Redis stream 'agent-logs' (MsgID: %s).", test_payload["trace_id"], msg_id)
    except Exception as exc:
        logger.error("[FAIL] Failed to write trace to Redis stream: %s", exc)
        conn.close()
        raise AssertionError(f"Redis xadd failed: {exc}")

    # 5. Test reading back from Redis Stream
    try:
        entries = r.xrevrange("agent-logs", count=1)
        assert len(entries) > 0, "No entries returned from xrevrange"
        logger.info("[PASS] Successfully read back from Redis stream 'agent-logs'.")
    except Exception as exc:
        logger.error("[FAIL] Failed to read from Redis stream: %s", exc)
        conn.close()
        raise AssertionError(f"Redis stream read failed: {exc}")

    # 6. Test inserting and querying row from PostgreSQL agent_evaluations
    try:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO agent_evaluations 
            (raw_payload, retrieval_time_ms, tool_accuracy, groundedness_score, hallucination_prob, is_hallucinated, answer_correctness, context_recall)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
            """, (Json(test_payload), 25.5, 1.0, 0.95, 0.02, 0, 0.92, 0.88))
            row_id = cur.fetchone()[0]

            cur.execute("SELECT id, retrieval_time_ms, is_hallucinated FROM agent_evaluations WHERE id = %s;", (row_id,))
            record = cur.fetchone()
            assert record is not None and record[0] == row_id

        conn.close()
        logger.info("[PASS] Successfully inserted and verified row ID %s in PostgreSQL 'agent_evaluations'.", row_id)
    except Exception as exc:
        logger.error("[FAIL] PostgreSQL insert/query test failed: %s", exc)
        conn.close()
        raise AssertionError(f"PostgreSQL insert/query verification failed: {exc}")

    logger.info("[PASS] Live Docker Infrastructure Connectivity & End-to-End Persistence Verified.")


if __name__ == "__main__":
    logger.info("Starting IMPARK Evaluator Verification Suite...")
    try:
        test_sentence_splitter()
        simulate_flow_1_interactive_chat()
        simulate_flow_2_golden_benchmark()
        test_live_docker_integration()
        logger.info("\n==================================================================")
        logger.info("[SUCCESS] All pipeline tests and metric evaluation mechanics VERIFIED!")
        logger.info("==================================================================")
    except Exception as exc:
        logger.error("\n==================================================================")
        logger.error("[FAIL] Pipeline Verification Failed: %s", exc)
        logger.error("==================================================================")
        sys.exit(1)
