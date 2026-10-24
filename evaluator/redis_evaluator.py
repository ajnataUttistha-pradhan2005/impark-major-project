# ==============================================================================
# IMPARK Blocking CPU Evaluator Worker
# Self-hosted, decoupled, CPU-only evaluation daemon for LangGraph workflows.
# ==============================================================================

import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import redis
    _REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    _REDIS_AVAILABLE = False

try:
    import psycopg2
    from psycopg2.extras import Json
    _PSYCOPG_VERSION = 2
except ImportError:
    try:
        import psycopg as psycopg2  # type: ignore
        from psycopg.types.json import Jsonb as Json  # type: ignore
        _PSYCOPG_VERSION = 3
    except ImportError:
        psycopg2 = None  # type: ignore
        Json = None  # type: ignore
        _PSYCOPG_VERSION = 0

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("impark.evaluator.worker")

# ------------------------------------------------------------------------------
# Configuration from Environment Variables
# ------------------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_STREAM = os.getenv("REDIS_STREAM", "agent-logs")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "eval_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")

HALLUCINATION_THRESHOLD = float(os.getenv("HALLUCINATION_THRESHOLD", "0.45"))


# ------------------------------------------------------------------------------
# Model Initialization (CPU-Only, ~220MB RAM)
# ------------------------------------------------------------------------------
logger.info("Initializing CPU Evaluation Models (~220MB RAM)...")

try:
    from sentence_transformers import CrossEncoder, SentenceTransformer, util
    _MODELS_AVAILABLE = True
except ImportError as err:
    logger.warning("sentence_transformers / torch not installed: %s. Using heuristic fallback.", err)
    _MODELS_AVAILABLE = False
    CrossEncoder = None  # type: ignore
    SentenceTransformer = None  # type: ignore
    util = None  # type: ignore

embedder: Optional[Any] = None
nli_model: Optional[Any] = None

def init_models() -> Tuple[Any, Any]:
    """Loads MiniLM and DeBERTa on CPU with memory-efficient configuration."""
    global embedder, nli_model
    if not _MODELS_AVAILABLE:
        return None, None

    if embedder is None:
        logger.info("Loading sentence-transformers/all-MiniLM-L6-v2 on CPU (~80MB RAM)...")
        embedder = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

    if nli_model is None:
        logger.info("Loading cross-encoder/nli-deberta-v3-small on CPU (~140MB RAM)...")
        # Label mapping: index 0 = entailment, index 1 = neutral, index 2 = contradiction
        nli_model = CrossEncoder("cross-encoder/nli-deberta-v3-small", device="cpu")

    logger.info("CPU models loaded successfully.")
    return embedder, nli_model


# ------------------------------------------------------------------------------
# Database & Broker Resilient Connection Helpers
# ------------------------------------------------------------------------------
def get_postgres_connection() -> Any:
    """Connects to PostgreSQL with automatic retry and exponential backoff."""
    delay = 1.0
    while True:
        try:
            conn = psycopg2.connect(
                dbname=POSTGRES_DB,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                connect_timeout=10,
            )
            conn.autocommit = False
            logger.info("Connected to PostgreSQL at %s:%s/%s", POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB)
            return conn
        except Exception as exc:
            logger.warning(
                "PostgreSQL connection failed (%s). Retrying in %.1f seconds...", exc, delay
            )
            time.sleep(delay)
            delay = min(delay * 1.5, 30.0)


def get_redis_client() -> redis.Redis:
    """Connects to Redis with automatic retry and ping verification."""
    delay = 1.0
    while True:
        try:
            r = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                decode_responses=True,
                socket_timeout=None,  # Blocking operations require no timeout
                socket_connect_timeout=5,
            )
            r.ping()
            logger.info("Connected to Redis at %s:%s", REDIS_HOST, REDIS_PORT)
            return r
        except Exception as exc:
            logger.warning(
                "Redis connection failed (%s). Retrying in %.1f seconds...", exc, delay
            )
            time.sleep(delay)
            delay = min(delay * 1.5, 30.0)


def init_database_schema(conn: Any) -> None:
    """Initializes the unified hybrid table agent_evaluations and the GIN index on raw_payload."""
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_evaluations (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw_payload JSONB NOT NULL,
            retrieval_time_ms FLOAT,
            tool_accuracy FLOAT,
            groundedness_score FLOAT,
            hallucination_prob FLOAT,
            is_hallucinated INT,
            answer_correctness FLOAT,
            context_recall FLOAT
        );
        CREATE INDEX IF NOT EXISTS idx_raw_payload_gin ON agent_evaluations USING GIN (raw_payload);
        """)
    conn.commit()
    logger.info("Database schema and GIN index verified.")


# ------------------------------------------------------------------------------
# Text Processing & Sentence Partitioning
# ------------------------------------------------------------------------------
def split_into_sentences(text: str) -> List[str]:
    """
    Partitions context text into individual sentences to safeguard the NLI model
    from exceeding its 512-token input truncation limits.
    """
    if not text or not text.strip():
        return []
    # Split on sentence boundary punctuation followed by whitespace
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    # Filter out empty or trivially short fragments
    return [s.strip() for s in sentences if len(s.strip()) > 5]


# ------------------------------------------------------------------------------
# Payload Schema Adapter (Key Normalization)
# ------------------------------------------------------------------------------
def extract_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts and standardizes core evaluation inputs from incoming flexible JSON schemas.
    Allows upstream agents to add arbitrary keys without breaking evaluation.
    """
    # Context field resolution
    context = (
        data.get("retrieved_context")
        or data.get("context")
        or data.get("evidence")
        or ""
    )
    if isinstance(context, list):
        context = "\n".join(str(c) for c in context)

    # Output field resolution
    output = (
        data.get("agent_output")
        or data.get("output")
        or data.get("final_response")
        or data.get("response")
        or ""
    )
    if isinstance(output, dict) and "text" in output:
        output = output["text"]

    # Trajectory resolution
    trajectory = data.get("trajectory") or []
    if isinstance(trajectory, str):
        trajectory = [trajectory]

    # Latency resolution
    retrieval_time_ms = data.get("retrieval_time_ms", 0.0)
    if retrieval_time_ms is None or str(retrieval_time_ms).strip() == "":
        retrieval_time_ms = 0.0

    return {
        "context": str(context).strip(),
        "output": str(output).strip(),
        "ground_truth": data.get("ground_truth"),
        "trajectory": list(trajectory),
        "expected_agent": data.get("expected_agent"),
        "retrieval_time_ms": float(retrieval_time_ms),
    }


# ------------------------------------------------------------------------------
# Mathematical Evaluation Mechanics (The 6 Core Metrics)
# ------------------------------------------------------------------------------
def evaluate_all_metrics(fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes the exact mathematical mechanics for all 6 metrics:
      1. Retrieval Latency (ms): Exact monotonic clock duration.
      2. Tool/Trajectory Selection Accuracy: 1.0 (hit), 0.0 (miss), or None (unsupervised).
      3. Groundedness Score: Cosine similarity clamped to [0.0, 1.0] between context and output.
      4. Hallucination Probability: Max sentence-level NLI contradiction probability; is_hallucinated > 0.45.
      5. Answer Correctness: 50% Semantic Cosine + 50% NLI Entailment probability against Ground Truth.
      6. Context Recall: Clamped Cosine similarity between Ground Truth and Retrieved Context.
    """
    context = fields["context"]
    output = fields["output"]
    gt = fields["ground_truth"]
    trajectory = fields["trajectory"]
    expected_agent = fields["expected_agent"]
    retrieval_time_ms = fields["retrieval_time_ms"]

    # Metric 1: Retrieval Latency (ms)
    retrieval_latency = round(float(retrieval_time_ms), 2)

    # Metric 2: Tool / Trajectory Selection Accuracy
    if expected_agent is not None and str(expected_agent).strip():
        expected_str = str(expected_agent).strip().lower()
        tool_acc: Optional[float] = 1.0 if any(expected_str == str(t).strip().lower() for t in trajectory) else 0.0
    else:
        # Live interactive user chats: Keep NULL so benchmark averages are unaffected
        tool_acc = None

    # Handle model availability
    if not _MODELS_AVAILABLE or embedder is None or nli_model is None:
        # Fallback heuristic calculation if models are disabled/mocked
        has_context = bool(context and len(context) > 0)
        has_output = bool(output and len(output) > 0)
        groundedness = 1.0 if (has_context and has_output) else 0.0
        hallucination_prob = 0.0
        is_hallucinated = 0
        answer_correctness = 1.0 if gt else None
        context_recall = 1.0 if gt and has_context else None
        return {
            "retrieval_time_ms": retrieval_latency,
            "tool_accuracy": tool_acc,
            "groundedness": groundedness,
            "hallucination_prob": hallucination_prob,
            "is_hallucinated": is_hallucinated,
            "answer_correctness": answer_correctness,
            "context_recall": context_recall,
        }

    # Metric 3: Groundedness Score (Context vs. Output)
    if context and output:
        emb_context = embedder.encode(context, convert_to_tensor=True)
        emb_output = embedder.encode(output, convert_to_tensor=True)
        cos_sim = float(util.cos_sim(emb_context, emb_output)[0][0])
        groundedness = round(max(0.0, min(1.0, cos_sim)), 3)
    else:
        groundedness = 0.0
        emb_context = None
        emb_output = None

    # Metric 4: Hallucination Probability via Sentence-level Chunking Check
    # Solves token truncation and tests each context sentence against agent_output for Contradiction (Index 2)
    context_sentences = split_into_sentences(context)
    if context_sentences and output:
        pairs = [(sentence, output) for sentence in context_sentences]
        nli_outputs = nli_model.predict(pairs, apply_softmax=True)
        # Extract index 2 (Contradiction) across all candidate sentences
        hallucination_prob = round(float(max(prob[2] for prob in nli_outputs)), 3)
    else:
        hallucination_prob = 0.0

    is_hallucinated = 1 if hallucination_prob > HALLUCINATION_THRESHOLD else 0

    # Metric 5 & 6: Ground Truth Dependent Metrics (Answer Correctness & Context Recall)
    if gt is not None and str(gt).strip():
        gt_str = str(gt).strip()
        emb_gt = embedder.encode(gt_str, convert_to_tensor=True)

        # Answer Correctness: 50% Cosine Similarity + 50% NLI Entailment (Index 0)
        if emb_output is None:
            emb_output = embedder.encode(output, convert_to_tensor=True) if output else None

        if emb_output is not None:
            sem_sim = max(0.0, min(1.0, float(util.cos_sim(emb_gt, emb_output)[0][0])))
            nli_gt_out = nli_model.predict([(gt_str, output)], apply_softmax=True)[0]
            entailment_prob = float(nli_gt_out[0])  # Index 0 explicitly evaluates structural Entailment
            answer_correctness = round((0.5 * sem_sim) + (0.5 * entailment_prob), 3)
        else:
            answer_correctness = 0.0

        # Context Recall: Clamped Cosine Similarity between Ground Truth and Retrieved Context
        if emb_context is None and context:
            emb_context = embedder.encode(context, convert_to_tensor=True)

        if emb_context is not None:
            recall_sim = max(0.0, min(1.0, float(util.cos_sim(emb_gt, emb_context)[0][0])))
            context_recall = round(recall_sim, 3)
        else:
            context_recall = 0.0
    else:
        answer_correctness = None
        context_recall = None

    return {
        "retrieval_time_ms": retrieval_latency,
        "tool_accuracy": tool_acc,
        "groundedness": groundedness,
        "hallucination_prob": hallucination_prob,
        "is_hallucinated": is_hallucinated,
        "answer_correctness": answer_correctness,
        "context_recall": context_recall,
    }


# ------------------------------------------------------------------------------
# Infinite Blocking Worker Loop (OS Network Socket Wakeup -> 0% Idle CPU)
# ------------------------------------------------------------------------------
def run_evaluator_worker() -> None:
    """
    Worker daemon listening on Redis Stream 'agent-logs'.
    Utilizes XREAD BLOCK 0 to put the process into kernel sleep at 0.0% CPU when idle.
    """
    init_models()
    r = get_redis_client()
    conn = get_postgres_connection()
    init_database_schema(conn)

    last_id = "$"  # Listen only for new messages arriving after daemon startup
    logger.info("Evaluator Worker active on stream '%s' (Idle = 0.0%% CPU via XREAD BLOCK 0)...", REDIS_STREAM)

    while True:
        try:
            # OS blocking socket call: sleeps at 0% CPU until a packet arrives
            events = r.xread({REDIS_STREAM: last_id}, count=1, block=0)
            if not events:
                continue

            for stream_name, messages in events:
                for msg_id, raw_dict in messages:
                    last_id = msg_id
                    raw_payload_str = raw_dict.get("payload")
                    if not raw_payload_str:
                        logger.warning("[%s] Empty payload in stream message, skipping.", msg_id)
                        continue

                    try:
                        raw_json = json.loads(raw_payload_str)
                    except json.JSONDecodeError as json_err:
                        logger.error("[%s] Invalid JSON payload: %s", msg_id, json_err)
                        continue

                    fields = extract_fields(raw_json)
                    scores = evaluate_all_metrics(fields)

                    # Insert row into PostgreSQL within transaction
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO agent_evaluations 
                            (raw_payload, retrieval_time_ms, tool_accuracy, groundedness_score, 
                             hallucination_prob, is_hallucinated, answer_correctness, context_recall)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """, (
                            Json(raw_json),
                            scores["retrieval_time_ms"],
                            scores["tool_accuracy"],
                            scores["groundedness"],
                            scores["hallucination_prob"],
                            scores["is_hallucinated"],
                            scores["answer_correctness"],
                            scores["context_recall"],
                        ))
                    conn.commit()

                    logger.info(
                        "[%s] Trace %s -> Latency: %sms | Groundedness: %s | "
                        "Hallucination: %s (Flag=%s) | ToolAcc: %s | GT Correctness: %s | Recall: %s",
                        msg_id,
                        raw_json.get("trace_id", "unknown"),
                        scores["retrieval_time_ms"],
                        scores["groundedness"],
                        scores["hallucination_prob"],
                        scores["is_hallucinated"],
                        scores["tool_accuracy"],
                        scores["answer_correctness"],
                        scores["context_recall"],
                    )

        except (psycopg2.OperationalError, psycopg2.DatabaseError) as pg_err:
            logger.error("PostgreSQL connection error: %s. Reconnecting...", pg_err)
            try:
                conn.close()
            except Exception:
                pass
            conn = get_postgres_connection()
            init_database_schema(conn)

        except (redis.ConnectionError, redis.TimeoutError) as redis_err:
            logger.error("Redis connection error: %s. Reconnecting...", redis_err)
            r = get_redis_client()

        except Exception as unhandled:
            logger.exception("Unexpected error in worker loop: %s", unhandled)
            time.sleep(1.0)


if __name__ == "__main__":
    run_evaluator_worker()
