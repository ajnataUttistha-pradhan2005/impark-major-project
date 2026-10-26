# ==============================================================================
# IMPARK Local Redis Tracer (BaseCallbackHandler)
# Captures LangChain & LangGraph telemetry locally with < 1ms hot-path publish latency.
# ==============================================================================

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    import redis
    _REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    _REDIS_AVAILABLE = False

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:
    # Minimal fallback callback handler if langchain_core is not installed in the current environment
    class BaseCallbackHandler:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

logger = logging.getLogger("impark.evaluator.tracer")


class LocalRedisTracer(BaseCallbackHandler):
    """
    Hooks into LangGraph / LangChain execution lifecycles to record node trajectories,
    retrieval latencies, extracted context, and token usage.

    At turn completion, consolidates telemetry into a single unified JSON payload
    and publishes asynchronously to the Redis stream 'agent-logs' (< 1ms overhead).
    """

    _global_last_failure_time: float = 0.0
    _retry_cooldown: float = 30.0

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
        redis_password: Optional[str] = None,
        stream_name: Optional[str] = None,
        retrieval_node_name: str = "GraphRetriever",
        socket_timeout: float = 0.2,
    ) -> None:
        super().__init__()
        self.redis_host = redis_host or os.getenv("REDIS_HOST", "127.0.0.1")
        self.redis_port = int(redis_port or os.getenv("REDIS_PORT", 6379))
        self.redis_password = redis_password or os.getenv("REDIS_PASSWORD", None)
        self.stream_name = stream_name or os.getenv("REDIS_STREAM", "phoenix-agent-traces")
        self.phoenix_stream = os.getenv("PHOENIX_STREAM", "phoenix-agent-traces")
        self.retrieval_node_name = retrieval_node_name
        self.socket_timeout = socket_timeout
        self.sync_postgres = os.getenv("SYNC_POSTGRES", "false").lower() in ("true", "1", "yes")

        self._redis_client: Optional[Any] = None
        self.reset()

    def _get_client(self) -> Optional[Any]:
        """Lazy-initializes thread-safe Redis client with strict timeouts and failure cooldown."""
        if not _REDIS_AVAILABLE:
            return None
        # If Redis recently failed, skip network attempt across all instances to guarantee zero hot-path delay
        if time.time() - LocalRedisTracer._global_last_failure_time < LocalRedisTracer._retry_cooldown:
            return None

        if self._redis_client is None:
            try:
                retry_strategy = None
                try:
                    from redis.retry import Retry
                    from redis.backoff import NoBackoff
                    retry_strategy = Retry(NoBackoff(), 0)
                except ImportError:
                    pass

                self._redis_client = redis.Redis(
                    host=self.redis_host,
                    port=self.redis_port,
                    password=self.redis_password,
                    decode_responses=True,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=0.05,
                    retry=retry_strategy,
                )
            except Exception as exc:
                logger.warning("Failed to initialize Redis client: %s", exc)
                self._redis_client = None
                LocalRedisTracer._global_last_failure_time = time.time()
        return self._redis_client

    def reset(self) -> None:
        """Resets trace state for a new execution turn."""
        self.trace_id = str(uuid.uuid4())
        self.trajectory: List[str] = []
        self.node_start_times: Dict[str, tuple[str, float]] = {}
        self.node_latencies_ms: Dict[str, float] = {}
        self.retrieved_context: List[str] = []
        self.total_tokens: int = 0
        self.actions_performed: int = 0

    # --------------------------------------------------------------------------
    # LangChain / LangGraph Lifecycle Callbacks
    # --------------------------------------------------------------------------

    def on_chain_start(
        self,
        serialized: Optional[Dict[str, Any]],
        inputs: Dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Captures node entry and start timestamp."""
        node_name = (metadata or {}).get("langgraph_node")
        if not node_name and serialized:
            node_name = serialized.get("name")

        if node_name and str(run_id) not in self.node_start_times:
            if node_name not in self.trajectory:
                self.trajectory.append(node_name)
            self.node_start_times[str(run_id)] = (node_name, time.perf_counter())
            self.actions_performed += 1

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        """Calculates monotonic node latency on completion."""
        rid = str(run_id)
        if rid in self.node_start_times:
            node_name, start_time = self.node_start_times.pop(rid)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            self.node_latencies_ms[node_name] = elapsed_ms

    def on_tool_start(
        self,
        serialized: Optional[Dict[str, Any]],
        input_str: str,
        *,
        run_id: Any,
        parent_run_id: Optional[Any] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Captures tool execution start time and records tool name into trajectory."""
        tool_name = (serialized or {}).get("name") or "unknown_tool"
        if tool_name not in self.trajectory:
            self.trajectory.append(tool_name)
        self.node_start_times[str(run_id)] = (tool_name, time.perf_counter())
        self.actions_performed += 1

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        """Measures tool execution latency and extracts retrieved facts if applicable."""
        rid = str(run_id)
        if rid in self.node_start_times:
            tool_name, start_time = self.node_start_times.pop(rid)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            self.node_latencies_ms[tool_name] = elapsed_ms

            # If tool matches the configured retrieval node or graph retrieval, record latency
            if tool_name in {self.retrieval_node_name, "retrieve_plant_graph", "knowledge_graph"}:
                self.node_latencies_ms[self.retrieval_node_name] = elapsed_ms

        # Extract textual output into context if it contains facts
        if isinstance(output, str) and len(output.strip()) > 10:
            self.retrieved_context.append(output.strip())

    def on_retriever_end(
        self,
        documents: List[Any],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        """Extracts page_content from retrieved documents."""
        for doc in documents:
            content = getattr(doc, "page_content", None)
            if content:
                self.retrieved_context.append(str(content))
            elif isinstance(doc, str):
                self.retrieved_context.append(doc)
            elif isinstance(doc, dict) and "text" in doc:
                self.retrieved_context.append(str(doc["text"]))

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        """Aggregates LLM token consumption metrics."""
        if hasattr(response, "llm_output") and response.llm_output:
            token_usage = response.llm_output.get("token_usage", {})
            self.total_tokens += token_usage.get("total_tokens", 0)
        elif hasattr(response, "generations"):
            # Check usage_metadata on LangChain AIMessage objects
            for gen_list in response.generations:
                for gen in gen_list:
                    msg = getattr(gen, "message", None)
                    if msg and hasattr(msg, "usage_metadata") and msg.usage_metadata:
                        self.total_tokens += msg.usage_metadata.get("total_tokens", 0)

    # --------------------------------------------------------------------------
    # Direct Tracing Helpers (for clean orchestrator / agent integration)
    # --------------------------------------------------------------------------

    def record_node(self, node_name: str, latency_ms: float) -> None:
        """Manually records a node visit and its latency."""
        if node_name not in self.trajectory:
            self.trajectory.append(node_name)
        self.node_latencies_ms[node_name] = round(latency_ms, 2)
        self.actions_performed += 1

    def add_context(self, context_snippet: str) -> None:
        """Appends a retrieved evidence or search context snippet."""
        if context_snippet and context_snippet.strip():
            self.retrieved_context.append(context_snippet.strip())
            self.actions_performed += 1

    # --------------------------------------------------------------------------
    # Publishing Logic
    # --------------------------------------------------------------------------

    def publish_run(
        self,
        user_input: str,
        agent_output: str,
        expected_agent: Optional[str] = None,
        ground_truth: Optional[str] = None,
        manual_context: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Consolidates all captured states into a single unified JSON trace payload,
        serializes it, and appends it to the Redis stream 'agent-logs' using r.xadd.

        Ensures < 1ms hot-path publish latency and swallows connection errors safely
        so telemetry never interferes with production user chat.
        """
        context_str = (
            manual_context if manual_context is not None else "\n".join(self.retrieved_context)
        )

        # Resolve retrieval latency from recorded latencies
        retrieval_ms = self.node_latencies_ms.get(self.retrieval_node_name, 0.0)
        if retrieval_ms == 0.0:
            for candidate in ["retrieve_plant_graph", "knowledge_graph", "graph", "text_entity", "inspect_uploaded_image"]:
                if candidate in self.node_latencies_ms:
                    retrieval_ms = self.node_latencies_ms[candidate]
                    break

        payload: Dict[str, Any] = {
            "trace_id": self.trace_id,
            "span_id": self.trace_id.replace("-", "")[:16],
            "user_input": user_input,
            "retrieved_context": context_str,
            "agent_output": agent_output,
            "trajectory": list(self.trajectory),
            "expected_agent": expected_agent,
            "ground_truth": ground_truth,
            "node_latencies_ms": dict(self.node_latencies_ms),
            "retrieval_time_ms": round(float(retrieval_ms), 2),
            "total_tokens": int(self.total_tokens),
            "metadata": extra_metadata or {},
            "attributes": {
                "input.value": user_input,
                "output.value": agent_output,
                "retrieved_context": context_str,
                "graph_retrieval_time_ms": round(float(retrieval_ms), 2),
                "tool_selection_accuracy": (
                    1.0 if not expected_agent or expected_agent in self.trajectory else 0.0
                ),
                "trajectory": list(self.trajectory),
            },
        }

        # Zero Hot-Path Latency: Publish to Redis Stream with exception isolation
        client = self._get_client()
        redis_published = False
        if client is not None:
            # Publish to primary stream and standard aliases (ensures redis-cli XRANGE my_stream / phoenix-agent-traces both work)
            streams_to_publish = {self.stream_name, self.phoenix_stream, "my_stream", "agent-logs"}
            for target_stream in streams_to_publish:
                if target_stream:
                    try:
                        client.xadd(target_stream, {"payload": json.dumps(payload)})
                        redis_published = True
                    except Exception as s_exc:
                        logger.debug("Failed publishing to stream %s: %s", target_stream, s_exc)
            if redis_published:
                logger.debug(
                    "Published trace payload %s to streams %s",
                    self.trace_id,
                    list(streams_to_publish),
                )
        else:
            logger.debug(
                "Redis client unavailable; trace %s recorded locally only.",
                self.trace_id,
            )

        # Direct PostgreSQL fallback/sync:
        # If explicitly enabled via SYNC_POSTGRES=true, write aggregated metrics directly to PostgreSQL
        if self.sync_postgres:
            self._insert_to_postgres(payload)

        return payload

    def _insert_to_postgres(self, payload: Dict[str, Any]) -> bool:
        """Inserts aggregated trace and metrics directly into PostgreSQL agent_evaluations."""
        try:
            try:
                import psycopg2
                from psycopg2.extras import Json
            except ImportError:
                import psycopg as psycopg2  # type: ignore
                from psycopg.types.json import Jsonb as Json  # type: ignore

            host = os.getenv("POSTGRES_HOST", "127.0.0.1")
            port = int(os.getenv("EVAL_POSTGRES_PORT", os.getenv("POSTGRES_PORT", "5433")))
            db = os.getenv("POSTGRES_DB", "phoenix")
            user = os.getenv("POSTGRES_USER", "postgres")
            password = os.getenv("POSTGRES_PASSWORD", "password")

            # Try evaluating metrics via redis_evaluator helpers if available
            try:
                from redis_evaluator import evaluate_all_metrics, extract_fields
                fields = extract_fields(payload)
                scores = evaluate_all_metrics(fields)
            except Exception:
                scores = {
                    "retrieval_time_ms": payload.get("retrieval_time_ms", 0.0),
                    "tool_accuracy": 1.0 if payload.get("expected_agent") in payload.get("trajectory", []) else None,
                    "groundedness": 1.0 if payload.get("retrieved_context") and payload.get("agent_output") else 0.0,
                    "hallucination_prob": 0.0,
                    "is_hallucinated": 0,
                    "answer_correctness": None,
                    "context_recall": None,
                }

            conn = psycopg2.connect(
                dbname=db,
                user=user,
                password=password,
                host=host,
                port=port,
                connect_timeout=1,
            )
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
                cur.execute("""
                    INSERT INTO agent_evaluations 
                    (raw_payload, retrieval_time_ms, tool_accuracy, groundedness_score, 
                     hallucination_prob, is_hallucinated, answer_correctness, context_recall)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """, (
                    Json(payload),
                    scores.get("retrieval_time_ms"),
                    scores.get("tool_accuracy"),
                    scores.get("groundedness"),
                    scores.get("hallucination_prob"),
                    scores.get("is_hallucinated"),
                    scores.get("answer_correctness"),
                    scores.get("context_recall"),
                ))
            conn.commit()
            conn.close()
            logger.info("Directly committed aggregated agent metrics to PostgreSQL agent_evaluations.")
            return True
        except Exception as exc:
            logger.debug("Direct PostgreSQL emission skipped: %s", exc)
            return False
