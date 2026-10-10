"""Reproducible retrieval evaluation; synthetic prompts, real imported catalog.

Run: python -m backend.evaluation.text_discovery [--semantic]
"""

import argparse
import asyncio
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4

from backend.agents.text.embeddings import FastEmbedProvider
from backend.agents.text.search import HybridNameSearch
from backend.database.postgres.client import PostgresClient
from backend.database.postgres.search import PostgresNameRepository
from backend.database.qdrant.client import QdrantStore
from backend.database.search_config import SearchSettings


async def evaluate(*, semantic: bool = False) -> dict[str, object]:
    config = SearchSettings()
    postgres = PostgresClient(config)
    vectors = QdrantStore(config) if semantic else None
    await postgres.open()
    try:
        repo = PostgresNameRepository(postgres)
        search = HybridNameSearch(repo, vectors, FastEmbedProvider(config) if semantic else None)
        cases = json.loads(
            await asyncio.to_thread(
                Path("data/evaluation/text_discovery_cases.json").read_text, encoding="utf-8"
            )
        )
        results = []
        for case in cases:
            start = perf_counter()
            candidates, stages = await search.resolve(case["query"])
            rank = next(
                (i + 1 for i, c in enumerate(candidates) if c.label == case["expected"]), None
            )
            auto = [c for c in candidates if c.confidence >= 0.95]
            results.append(
                {
                    **case,
                    "rank": rank,
                    "latency_ms": round((perf_counter() - start) * 1000, 2),
                    "false_auto_resolution": any(
                        c.label != case["expected"] or case.get("confirm", False) for c in auto
                    ),
                    "candidates": [c.model_dump(mode="json") for c in candidates],
                    "stages": stages,
                }
            )
        positives = [r for r in results if r["expected"] is not None]
        latencies = sorted(r["latency_ms"] for r in results)
        report: dict[str, object] = {
            "evaluation_id": str(uuid4()),
            "suite": "synthetic-prompts-real-catalog-v1",
            "generation": str(await repo.generation()),
            "semantic": semantic,
            "case_count": len(results),
            "positive_cases": len(positives),
            "recall_at_5": sum(r["rank"] is not None for r in positives) / len(positives),
            "mrr": sum(1 / r["rank"] if r["rank"] else 0 for r in positives) / len(positives),
            "false_auto_resolutions": sum(r["false_auto_resolution"] for r in results),
            "latency_p50_ms": median(latencies),
            "latency_p95_ms": latencies[int((len(latencies) - 1) * 0.95)],
            "limitations": "Small synthetic suite; no clinical or general accuracy claim.",
            "cases": results,
        }
        path = Path("data/evaluation/text_discovery_report.json")
        await asyncio.to_thread(
            path.write_text, json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        from uuid import UUID

        await postgres.write(
            "INSERT INTO text_evaluation(evaluation_id,report) VALUES($1,$2::jsonb)",
            UUID(str(report["evaluation_id"])),
            json.dumps(report),
        )
        return {k: v for k, v in report.items() if k != "cases"}
    finally:
        if vectors:
            await vectors.close()
        await postgres.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(evaluate(semantic=args.semantic)), indent=2))
