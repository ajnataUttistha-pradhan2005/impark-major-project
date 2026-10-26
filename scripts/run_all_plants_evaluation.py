"""All Plants Question Evaluation Runner for IMPARK Deep Agents.

Executes natural-language evaluation questions across all plant names using the
existing Deep Agents conversation pipeline. Generates the full Cartesian product
of plants and evaluation questions, bypassing plant-identification stages and
persisting verified traces and responses incrementally.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.api.schemas.chat import ChatRequest
from backend.main import create_app
from backend.runtime import loop_factory
from scripts.run_evaluation import (
    EvaluationTraceCallback,
    build_structured_trace,
    load_xlsx_records,
    parse_identifier,
    redact_sensitive,
    utc_iso_now,
)

logger = logging.getLogger("impark.evaluation.all_plants")


def load_all_plant_names(plants_path: Path) -> list[str]:
    """Load canonical plant names from JSON file preserving order and uniqueness."""
    if not plants_path.exists():
        raise FileNotFoundError(f"Plant names file not found: {plants_path}")

    with open(plants_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    plant_names: list[str] = []
    seen: set[str] = set()

    for item in data:
        name = ""
        if isinstance(item, dict) and "plant_name" in item:
            name = str(item["plant_name"]).strip()
        elif isinstance(item, str):
            name = item.strip()

        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            plant_names.append(name)

    return plant_names


def load_all_questions(questions_path: Path) -> list[dict[str, Any]]:
    """Load evaluation questions and identifier arrays from Excel, JSON, or CSV."""
    if not questions_path.exists():
        raise FileNotFoundError(f"Questions file not found: {questions_path}")

    suffix = questions_path.suffix.lower()
    raw_records: list[dict[str, Any]] = []

    if suffix in (".xlsx", ".xlsm"):
        raw_records = load_xlsx_records(questions_path)
    elif suffix == ".json":
        with open(questions_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_records = data if isinstance(data, list) else [data]
    elif suffix == ".jsonl":
        with open(questions_path, "r", encoding="utf-8") as f:
            raw_records = [json.loads(line) for line in f if line.strip()]
    elif suffix == ".csv":
        import csv
        with open(questions_path, "r", encoding="utf-8") as f:
            raw_records = list(csv.DictReader(f))
    else:
        raise ValueError(f"Unsupported questions file format: {suffix}")

    questions: list[dict[str, Any]] = []
    for r in raw_records:
        q_text = str(r.get("question", "")).strip()
        if not q_text:
            continue
        raw_id = r.get("identifier")
        parsed_id = parse_identifier(raw_id)
        questions.append({
            "question": q_text,
            "identifier": parsed_id,
        })

    return questions


def generate_cartesian_combinations(
    plant_names: list[str],
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate Cartesian product: every plant name evaluated against every question."""
    combinations: list[dict[str, Any]] = []
    for plant in plant_names:
        for q_item in questions:
            combinations.append({
                "plant_name": plant,
                "question": q_item["question"],
                "identifier": list(q_item["identifier"]),
            })
    return combinations


def load_completed_and_failed_keys(
    output_path: Path,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Read existing output JSONL file to distinguish completed successful cases from failures."""
    completed: set[tuple[str, str]] = set()
    failed: set[tuple[str, str]] = set()

    if not output_path.exists():
        return completed, failed

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    p = str(obj.get("plant_name", "")).strip()
                    q = str(obj.get("question", "")).strip()
                    resp = str(obj.get("response", "")).strip()
                    if p and q and "traces" in obj and "identifier" in obj:
                        if resp.startswith("[ERROR]"):
                            failed.add((p, q))
                        else:
                            completed.add((p, q))
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Failed to read existing progress from {output_path}: {e}")

    return completed, failed


async def run_all_plants_evaluation(
    questions_path: Path,
    plants_path: Path,
    output_path: Path,
    limit: int | None = None,
    offset: int = 0,
    resume: bool = True,
    summary_report: bool = True,
) -> dict[str, Any]:
    """Execute all plant questions through the Deep Agents pipeline."""
    start_total_time = time.perf_counter()
    start_iso = utc_iso_now()

    # 1. Load inputs
    plants = load_all_plant_names(plants_path)
    questions = load_all_questions(questions_path)
    all_combinations = generate_cartesian_combinations(plants, questions)
    total_expected = len(all_combinations)

    print("\n" + "=" * 70)
    print("IMPARK ALL PLANTS QUESTION EVALUATION RUNNER")
    print("=" * 70)
    print(f"Plants file:               {plants_path} ({len(plants)} plants)")
    print(f"Questions file:            {questions_path} ({len(questions)} questions)")
    print(f"Total combinations:        {total_expected} cases (Cartesian product: {len(plants)} x {len(questions)})")
    print(f"Output destination:        {output_path}")
    print(f"Resume enabled:            {resume}")
    if limit is not None:
        print(f"Execution limit:           {limit} new cases")
    if offset > 0:
        print(f"Execution offset:          {offset}")
    print("=" * 70 + "\n")

    # 2. Check existing progress if resuming
    completed_keys, failed_keys = load_completed_and_failed_keys(output_path) if resume else (set(), set())
    if completed_keys:
        logger.info("Found %d previously completed successful cases.", len(completed_keys))
    if failed_keys:
        logger.info("Found %d previously failed cases (will be retried).", len(failed_keys))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_file_mode = "a" if resume else "w"

    # 3. Apply starting offset
    if offset > 0:
        all_combinations = all_combinations[offset:]
        logger.info("Applied offset %d (remaining combinations: %d)", offset, len(all_combinations))

    stats: dict[str, Any] = {
        "plants_loaded": len(plants),
        "questions_loaded": len(questions),
        "expected_total_combinations": total_expected,
        "total_evaluated_in_run": 0,
        "successful": 0,
        "failed": 0,
        "skipped_completed": 0,
        "start_time": start_iso,
    }

    # 4. Initialize application lifespan and entity catalog
    app = create_app()

    async with app.router.lifespan_context(app):
        service = app.state.conversations

        # Resolve entity catalog for plant identification bypass
        provider = service.harness.execution.text.provider
        _, records = await provider.catalog()
        catalog_by_name: dict[str, Any] = {
            r.plant_name.casefold(): r for r in records
        }
        for r in records:
            if r.normalized_name:
                catalog_by_name.setdefault(r.normalized_name.casefold(), r)
            if r.source_normalized_alias:
                catalog_by_name.setdefault(r.source_normalized_alias.casefold(), r)

        with open(output_path, out_file_mode, encoding="utf-8") as out_f:
            for idx, tc in enumerate(all_combinations, 1):
                # Check execution limit
                if limit is not None and stats["total_evaluated_in_run"] >= limit:
                    logger.info("Reached evaluation limit of %d new cases. Stopping.", limit)
                    break

                plant_name = tc["plant_name"]
                question = tc["question"]
                identifier = tc["identifier"]

                # Check if already successfully completed
                if resume and (plant_name, question) in completed_keys:
                    stats["skipped_completed"] += 1
                    continue

                case_num = stats["total_evaluated_in_run"] + 1
                logger.info(
                    "[Prog: %d/%d | Eval: %d | Done: %d | Fail: %d | Skip: %d] Plant='%s' | Q='%s'",
                    idx,
                    len(all_combinations),
                    case_num,
                    stats["successful"],
                    stats["failed"],
                    stats["skipped_completed"],
                    plant_name,
                    question[:50],
                )

                case_start_iso = utc_iso_now()
                case_start_time = time.perf_counter()

                # Bypass identification: look up plant canonical ID in catalog
                plant_rec = catalog_by_name.get(plant_name.casefold())
                if plant_rec is None:
                    error_msg = f"Unknown plant '{plant_name}' not found in entity catalog"
                    logger.error(error_msg)
                    case_end_iso = utc_iso_now()
                    elapsed_case_ms = round((time.perf_counter() - case_start_time) * 1000, 2)
                    err_trace = build_structured_trace(
                        plant_name=plant_name,
                        question=question,
                        trace_cb=EvaluationTraceCallback(),
                        app_trace_events=[],
                        state=None,
                        turn_resp=None,
                        case_start_iso=case_start_iso,
                        case_end_iso=case_end_iso,
                        elapsed_case_ms=elapsed_case_ms,
                        error=ValueError(error_msg),
                    )
                    result_obj = {
                        "plant_name": plant_name,
                        "question": question,
                        "identifier": identifier,
                        "traces": err_trace,
                        "response": f"[ERROR] {error_msg}",
                    }
                    out_f.write(json.dumps(result_obj, default=str, ensure_ascii=False) + "\n")
                    out_f.flush()
                    stats["total_evaluated_in_run"] += 1
                    stats["failed"] += 1
                    continue

                trace_cb = EvaluationTraceCallback()

                # Attach callback handler to conversation config for this turn
                orig_config = service._config
                service._config = lambda st: {**orig_config(st), "callbacks": [trace_cb]}

                final_response_text = ""
                structured_traces: dict[str, Any] = {}

                try:
                    # 1. Create a dedicated conversation session
                    cid = uuid4()
                    init_resp = await service.create(cid)
                    sid = init_resp.correlation.session_id

                    # 2. Submit turn with pre-selected plant ID (bypasses identification)
                    req = ChatRequest(text=question, selected_plant_id=plant_rec.plant_id)
                    turn_resp = await service.submit(sid, req, uuid4())

                    # 3. Capture natural-language response
                    if turn_resp.response:
                        final_response_text = turn_resp.response.text
                    else:
                        final_response_text = "[No final response returned]"

                    # 4. Integrate state & durable trace recorder events
                    st = await service.load(sid)
                    app_trace_events = await service.trace_events(sid)
                    case_end_iso = utc_iso_now()
                    elapsed_case_ms = round((time.perf_counter() - case_start_time) * 1000, 2)

                    structured_traces = build_structured_trace(
                        plant_name=plant_name,
                        question=question,
                        trace_cb=trace_cb,
                        app_trace_events=app_trace_events,
                        state=st,
                        turn_resp=turn_resp,
                        case_start_iso=case_start_iso,
                        case_end_iso=case_end_iso,
                        elapsed_case_ms=elapsed_case_ms,
                    )

                    stats["successful"] += 1

                except Exception as exc:
                    case_end_iso = utc_iso_now()
                    elapsed_case_ms = round((time.perf_counter() - case_start_time) * 1000, 2)
                    logger.exception("Evaluation turn failed for '%s' - '%s'", plant_name, question)
                    final_response_text = f"[ERROR] Execution failed: {type(exc).__name__}: {str(exc)}"
                    structured_traces = build_structured_trace(
                        plant_name=plant_name,
                        question=question,
                        trace_cb=trace_cb,
                        app_trace_events=[],
                        state=None,
                        turn_resp=None,
                        case_start_iso=case_start_iso,
                        case_end_iso=case_end_iso,
                        elapsed_case_ms=elapsed_case_ms,
                        error=exc,
                    )
                    stats["failed"] += 1
                finally:
                    service._config = orig_config

                # Save record incrementally with EXACTLY the 5 required top-level fields
                result_obj = {
                    "plant_name": plant_name,
                    "question": question,
                    "identifier": identifier,
                    "traces": structured_traces,
                    "response": final_response_text,
                }

                out_f.write(json.dumps(result_obj, default=str, ensure_ascii=False) + "\n")
                out_f.flush()
                stats["total_evaluated_in_run"] += 1

    stats["end_time"] = utc_iso_now()
    stats["total_elapsed_seconds"] = round(time.perf_counter() - start_total_time, 2)
    stats["cases_remaining"] = max(
        0,
        total_expected - (len(completed_keys) + stats["successful"]),
    )

    # Print summary
    print("\n" + "=" * 70)
    print("EVALUATION RUN COMPLETE")
    print("=" * 70)
    print(f"Number of plants loaded:          {stats['plants_loaded']}")
    print(f"Number of questions loaded:       {stats['questions_loaded']}")
    print(f"Expected total combinations:      {stats['expected_total_combinations']}")
    print(f"Evaluated in this run:            {stats['total_evaluated_in_run']}")
    print(f"Successfully completed cases:     {stats['successful']}")
    print(f"Failed cases:                     {stats['failed']}")
    print(f"Cases skipped (already done):     {stats['skipped_completed']}")
    print(f"Cases remaining:                  {stats['cases_remaining']}")
    print(f"Output file location:             {output_path}")
    print(f"Total elapsed time:               {stats['total_elapsed_seconds']}s")
    print("=" * 70 + "\n")

    if summary_report:
        summary_path = output_path.with_suffix(".summary.json")
        try:
            with open(summary_path, "w", encoding="utf-8") as sf:
                json.dump(stats, sf, indent=2)
            logger.info("Summary report written to %s", summary_path)
        except Exception as e:
            logger.warning("Could not write summary report: %s", e)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run evaluation questions across all medicinal plants using the IMPARK Deep Agents pipeline."
    )
    parser.add_argument(
        "--questions",
        "--input",
        "-q",
        "-i",
        type=Path,
        default=Path("evaluation-job-1/test_data.xlsx"),
        help="Path to questions dataset (.xlsx, .json, .jsonl, .csv)",
    )
    parser.add_argument(
        "--plants",
        "-p",
        type=Path,
        default=Path("evaluation-job-1/plant_names.json"),
        help="Path to plant names JSON file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("data/all_plants_evaluation.jsonl"),
        help="Path to output JSONL file (default: data/all_plants_evaluation.jsonl)",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Maximum number of new cases to evaluate in this run",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Starting index offset in the Cartesian combination list",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable resume mode (overwrites output file rather than appending)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(
        run_all_plants_evaluation(
            questions_path=args.questions,
            plants_path=args.plants,
            output_path=args.output,
            limit=args.limit,
            offset=args.offset,
            resume=not args.no_resume,
        ),
        loop_factory=loop_factory,
    )


if __name__ == "__main__":
    main()
