# ==============================================================================
# IMPARK Test Suite: Phoenix & OpenTelemetry Evaluator Verification
# Tests all 4 core metrics, Redis Stream queueing, and sequential judge lifecycle
# ==============================================================================

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import asyncio

from phoenix_pipeline import (
    IdleAwareEvaluationJudge,
    RedisStreamSpanExporter,
    execute_agent_pipeline,
    execute_real_graph_retrieval,
)


class TestPhoenixPipelineMetrics(unittest.TestCase):
    """Verifies all 4 evaluation metrics and core system constraints."""

    def test_metric_1_graph_retrieval_time(self):
        """
        Verifies Metric 1: graph_retrieval_time is accurately tracked using
        Python time.perf_counter inside the REAL GraphAgent execution step.
        """
        facts = asyncio.run(execute_real_graph_retrieval("Query Withania phytochemicals", plant_id="withania_somnifera"))
        
        self.assertIn("retrieval_time_ms", facts)
        self.assertIsInstance(facts["retrieval_time_ms"], float)
        self.assertGreater(facts["retrieval_time_ms"], 0.0, "Real GraphAgent execution must have measured latency > 0ms.")
        self.assertIn("evidence_claims", facts)
        self.assertGreaterEqual(len(facts["evidence_claims"]), 1)

    def test_metric_2_tool_selection_accuracy(self):
        """
        Verifies Metric 2: tool_selection_accuracy returns binary 1.0 or 0.0
        based on comparing selected tool against expected ground truth.
        """
        # Case A: Correct Tool Matching -> 1.0
        res_match = execute_agent_pipeline(
            user_query="Query knowledge graph for Withania somnifera details",
            expected_tool="query_knowledge_graph",
        )
        self.assertEqual(res_match["tool_selection_accuracy"], 1.0)

        # Case B: Tool Mismatch -> 0.0
        res_mismatch = execute_agent_pipeline(
            user_query="Query knowledge graph for Withania somnifera details",
            expected_tool="search_text_embeddings",
        )
        self.assertEqual(res_mismatch["tool_selection_accuracy"], 0.0)

    def test_metrics_3_and_4_groundedness_and_hallucination_rate(self):
        """
        Verifies Metric 3 (groundedness) and Metric 4 (hallucination_rate):
        - Sequential judge evaluates grounding under strict JSON format constraints.
        - hallucination_rate is the mathematical inverse of groundedness.
        """
        judge = IdleAwareEvaluationJudge(redis_client=None, postgres_conn=None)

        context = (
            "Plant: Withania somnifera (Ashwagandha). "
            "Bioactive compounds: Withanolides, Withaferin A. "
            "Indications: Adaptogen, stress relief, neuroprotective."
        )

        # Case A: Factual, fully grounded output
        grounded_output = (
            "Withania somnifera contains withanolides and withaferin A, "
            "providing adaptogenic neuroprotection and stress alleviation."
        )
        g_score, h_score, reasoning = judge.evaluate_groundedness_with_judge(
            context=context,
            user_query="What does Ashwagandha do?",
            agent_output=grounded_output,
        )

        self.assertGreaterEqual(g_score, 0.7, "Factual content should receive high groundedness.")
        self.assertLessEqual(h_score, 0.3, "Factual content should receive low hallucination rate.")
        self.assertAlmostEqual(g_score + h_score, 1.0, delta=0.05, msg="Hallucination rate must be inverse of groundedness.")
        self.assertIsInstance(reasoning, str)

        # Case B: Hallucinated / Unsupported claims
        hallucinated_output = (
            "Withania somnifera contains synthetic caffeine and cure-all nanobots "
            "capable of instant cardiac surgery."
        )
        g_bad, h_bad, _ = judge.evaluate_groundedness_with_judge(
            context=context,
            user_query="What does Ashwagandha do?",
            agent_output=hallucinated_output,
        )

        self.assertLessEqual(g_bad, 0.4, "Fabricated content must receive low groundedness.")
        self.assertGreaterEqual(h_bad, 0.6, "Fabricated content must receive high hallucination rate.")

    def test_redis_stream_span_exporter_queue(self):
        """
        Verifies Queuing Mechanism: OpenTelemetry spans are serialized and pushed
        into Redis Streams asynchronously via XADD with zero blocking.
        """
        mock_redis = MagicMock()
        exporter = RedisStreamSpanExporter(redis_client=mock_redis, stream_name="test-stream")

        mock_span = MagicMock()
        mock_span.get_span_context.return_value.trace_id = 0x1234567890ABCDEF1234567890ABCDEF
        mock_span.get_span_context.return_value.span_id = 0x1234567890ABCDEF
        mock_span.parent = None
        mock_span.name = "test_agent_span"
        mock_span.start_time = 1000000000
        mock_span.end_time = 1050000000
        mock_span.attributes = {"input.value": "Test input", "graph_retrieval_time_ms": 35.5}
        mock_span.status = None

        res = exporter.export([mock_span])

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args[0]
        self.assertEqual(call_args[0], "test-stream")
        
        payload = json.loads(call_args[1]["payload"])
        self.assertEqual(payload["name"], "test_agent_span")
        self.assertEqual(payload["attributes"]["graph_retrieval_time_ms"], 35.5)

    def test_idle_aware_worker_single_item_lifecycle(self):
        """
        Verifies Idle-Aware Sequential Worker:
        Wakes up from stream entry, computes all 4 metrics sequentially,
        and logs to destination backends.
        """
        judge = IdleAwareEvaluationJudge(redis_client=None, postgres_conn=None)

        stream_entry = {
            "payload": json.dumps(
                {
                    "trace_id": "0123456789abcdef0123456789abcdef",
                    "span_id": "0123456789abcdef",
                    "attributes": {
                        "input.value": "Ashwagandha compounds",
                        "output.value": "Ashwagandha contains withanolides.",
                        "retrieved_context": "Withania somnifera (Ashwagandha) contains withanolides.",
                        "graph_retrieval_time_ms": 41.5,
                        "tool_selection_accuracy": 1.0,
                    },
                }
            )
        }

        result = judge.process_trace_item(stream_entry)

        self.assertEqual(result["graph_retrieval_time"], 41.5)
        self.assertEqual(result["tool_selection_accuracy"], 1.0)
        self.assertGreaterEqual(result["groundedness"], 0.7)
        self.assertLessEqual(result["hallucination_rate"], 0.3)


if __name__ == "__main__":
    unittest.main()
