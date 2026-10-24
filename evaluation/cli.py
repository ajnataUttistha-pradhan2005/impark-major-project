"""Command-line interface for the standalone evaluation service."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr

from evaluation.config import EvaluationConfig
from evaluation.ground_truth import load_ground_truth_file
from evaluation.loader import InMemoryEvaluationLoader, PostgresEvaluationLoader
from evaluation.models import EvaluationResult, EvaluationTurn, GroundTruthTestCase
from evaluation.service import EvaluationService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="IMPARK Standalone Evaluation Service CLI"
    )
    parser.add_argument(
        "--ground-truth",
        "-g",
        type=str,
        required=True,
        help="Path to ground truth JSON or YAML file",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="PostgreSQL connection string (overrides DATABASE_URL in .env)",
    )
    parser.add_argument(
        "--fixture-turns",
        type=str,
        default=None,
        help="Path to offline JSON file containing app_turn fixtures (bypasses database)",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Filter evaluation to a specific session UUID",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Filter evaluation to a specific run UUID",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum turns to load from database (default: 100)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Path to save evaluation report JSON",
    )
    return parser.parse_args()


async def evaluate_from_db(
    config: EvaluationConfig,
    session_id: UUID | None,
    run_id: UUID | None,
    limit: int,
) -> list[EvaluationTurn]:
    """Load turns from PostgreSQL."""
    db_loader = PostgresEvaluationLoader(config)
    try:
        await db_loader.open()
        return await db_loader.load_turns(
            session_id=session_id,
            run_id=run_id,
            limit=limit,
        )
    finally:
        await db_loader.close()


def print_report(result: EvaluationResult) -> None:
    """Print human-readable evaluation summary."""
    cov = result.coverage
    print("\n" + "=" * 65)
    print("           IMPARK MULTI-AGENT EVALUATION REPORT")
    print("=" * 65)
    print(f"Evaluation ID : {result.evaluation_id}")
    print(f"Timestamp     : {result.created_at}")
    print("-" * 65)
    print("METRICS:")
    routing_str = (
        str(result.routing_accuracy)
        if result.routing_accuracy is not None
        else "null (uncomputable)"
    )
    precision_str = (
        str(result.graph_precision)
        if result.graph_precision is not None
        else "null (uncomputable)"
    )
    groundedness_str = (
        str(result.groundedness)
        if result.groundedness is not None
        else "null (evaluator unconfigured)"
    )
    hallucination_str = (
        str(result.hallucination_rate)
        if result.hallucination_rate is not None
        else "null (evaluator unconfigured)"
    )
    print(f"  • Orchestrator Routing Accuracy : {routing_str}")
    print(f"  • Graph Retrieval Precision     : {precision_str}")
    print(f"  • Groundedness (G)              : {groundedness_str}")
    print(f"  • Hallucination Rate (HR)       : {hallucination_str}")
    print("-" * 65)
    print("COVERAGE:")
    print(f"  • Total Test Cases   : {cov.total_cases}")
    print(f"  • Matched Turns      : {cov.matched_turns}")
    print(f"  • Missing Turns      : {cov.missing_turns}")
    print(f"  • Incomplete Turns   : {cov.incomplete_turns}")
    print(f"  • Evaluated Turns    : {cov.evaluated_turns}")
    print(f"  • Skipped Turns      : {cov.skipped_turns}")
    print(f"  • Turn Coverage Rate : {cov.turn_coverage * 100:.1f}%")
    print(f"  • Total Claims       : {cov.total_claims} (Evaluable: {cov.evaluable_claims})")
    print("=" * 65)

    if result.diagnostics:
        print(f"Diagnostics emitted: {len(result.diagnostics)}")
        for d in result.diagnostics[:5]:
            print(f"  [{d.code}] {d.message}")
        if len(result.diagnostics) > 5:
            print(f"  ... and {len(result.diagnostics) - 5} more.")


def main() -> None:
    args = parse_args()

    # Load ground truth synchronously before entering async loop
    gt_path = Path(args.ground_truth)
    if not gt_path.exists():
        print(f"Error: Ground truth file not found: {gt_path}", file=sys.stderr)
        sys.exit(1)

    try:
        ground_truth: list[GroundTruthTestCase] = load_ground_truth_file(gt_path)
    except Exception as exc:
        print(f"Error loading ground truth file: {exc}", file=sys.stderr)
        sys.exit(1)

    session_uuid = UUID(args.session_id) if args.session_id else None
    run_uuid = UUID(args.run_id) if args.run_id else None

    # Load turns either from fixture or live PostgreSQL
    turns: list[EvaluationTurn] = []
    if args.fixture_turns:
        fixture_path = Path(args.fixture_turns)
        if not fixture_path.exists():
            print(f"Error: Fixture file not found: {fixture_path}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(fixture_path, encoding="utf-8") as f:
                data = json.load(f)
            fixture_rows = data if isinstance(data, list) else [data]
            loader = InMemoryEvaluationLoader(app_turns=fixture_rows)
            turns = loader.load_turns(session_id=session_uuid, run_id=run_uuid)
        except Exception as exc:
            print(f"Error loading turn fixture: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        config = EvaluationConfig()
        if args.db_url:
            config.database_url = SecretStr(args.db_url)

        if not config.database_url:
            print(
                "Error: No database URL provided. Provide --db-url, "
                "set DATABASE_URL, or use --fixture-turns.",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            turns = asyncio.run(
                evaluate_from_db(
                    config=config,
                    session_id=session_uuid,
                    run_id=run_uuid,
                    limit=args.limit,
                )
            )
        except Exception as exc:
            print(f"Database error during load: {exc}", file=sys.stderr)
            sys.exit(1)

    service = EvaluationService()
    result = asyncio.run(
        service.evaluate_batch(turns=turns, ground_truth=ground_truth)
    )

    print_report(result)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nFull evaluation report saved to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
