"""Validation script for IMPARK Plant Question Evaluation results.

Validates that JSONL output files meet all strict requirements:
1. Exactly 5 top-level keys: plant_name, question, identifier, traces, response.
2. identifier is an array of strings preserving original input values.
3. Tool calling, reasoning, and routing match actual execution without discrepancy.
4. Timestamps are valid ISO 8601 and monotonically non-decreasing.
5. Query types match actual question domain (e.g. GET_PHYTOCHEMICALS, GET_THERAPEUTIC_USES).
6. No unexpected duplicate test cases.
7. Diagnostic traces and 5-field schema are preserved even for failed cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

EXPECTED_TOP_KEYS = ["plant_name", "question", "identifier", "traces", "response"]
EXPECTED_TRACE_SECTIONS = ["tool_calling", "reasoning", "routing", "timeline"]


def parse_iso(ts_str: str) -> datetime:
    """Parse ISO 8601 string to datetime."""
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def validate_evaluation_file(
    file_path: Path,
    strict_no_errors: bool = False,
) -> dict[str, Any]:
    """Validate a JSONL evaluation file and return summary metrics."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    records: list[dict[str, Any]] = []
    seen_successful_cases: set[tuple[str, str]] = set()

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {line_num} in {file_path} is invalid JSON: {exc}")
            records.append(rec)

    if not records:
        raise ValueError(f"Evaluation file {file_path} is empty")

    validation_report: dict[str, Any] = {
        "total_records": len(records),
        "successful_records": 0,
        "failed_records": 0,
        "cases_validated": [],
        "errors": [],
    }

    for idx, rec in enumerate(records, 1):
        case_info = f"Record #{idx} (Plant='{rec.get('plant_name')}', Question='{str(rec.get('question'))[:40]}...')"

        # 1. Check top-level keys
        actual_keys = list(rec.keys())
        if actual_keys != EXPECTED_TOP_KEYS:
            diff = set(actual_keys) ^ set(EXPECTED_TOP_KEYS)
            raise AssertionError(
                f"{case_info}: Keys mismatch! Expected exactly {EXPECTED_TOP_KEYS}, got {actual_keys}. Discrepancy: {diff}"
            )

        plant_name = rec["plant_name"]
        question = rec["question"]
        identifier = rec["identifier"]
        traces = rec["traces"]
        response = rec["response"]

        # Check plant_name and question
        if not isinstance(plant_name, str) or not plant_name.strip():
            raise AssertionError(f"{case_info}: plant_name must be non-empty string, got {repr(plant_name)}")
        if not isinstance(question, str) or not question.strip():
            raise AssertionError(f"{case_info}: question must be non-empty string, got {repr(question)}")

        # 2. Check identifier
        if not isinstance(identifier, list):
            raise AssertionError(
                f"{case_info}: identifier must be an array of strings, got {type(identifier).__name__}: {repr(identifier)}"
            )
        for item in identifier:
            if not isinstance(item, str) or not item.strip():
                raise AssertionError(
                    f"{case_info}: Every identifier item must be a non-empty string, found {type(item).__name__}: {repr(item)}"
                )

        # 3. Check response
        if not isinstance(response, str) or not response.strip():
            raise AssertionError(f"{case_info}: response must be non-empty string")

        is_error_response = response.startswith("[ERROR]")
        if is_error_response:
            validation_report["failed_records"] += 1
            if strict_no_errors:
                raise AssertionError(f"{case_info}: Record contains error response: {response[:200]}")
        else:
            validation_report["successful_records"] += 1
            case_key = (plant_name.strip(), question.strip())
            if case_key in seen_successful_cases:
                raise AssertionError(f"{case_info}: Duplicate successful test case found for {case_key}")
            seen_successful_cases.add(case_key)

        # 4. Check traces structure
        if not isinstance(traces, dict):
            raise AssertionError(f"{case_info}: traces must be a dictionary, got {type(traces).__name__}")

        for sec in EXPECTED_TRACE_SECTIONS:
            if sec not in traces:
                raise AssertionError(f"{case_info}: Missing trace section '{sec}'")
            if not isinstance(traces[sec], list):
                raise AssertionError(f"{case_info}: Trace section '{sec}' must be a list")

        tool_calling = traces["tool_calling"]
        reasoning = traces["reasoning"]
        routing = traces["routing"]
        timeline = traces["timeline"]

        if not reasoning:
            raise AssertionError(f"{case_info}: reasoning list cannot be empty")
        if not routing:
            raise AssertionError(f"{case_info}: routing list cannot be empty")

        # 5. Check tool calling details (for non-fatal turns)
        observed_query_types: list[str] = []
        observed_subagents: list[str] = []

        for tc_idx, tc in enumerate(tool_calling, 1):
            for required_field in ["step", "tool_name", "agent", "arguments", "result", "status"]:
                if required_field not in tc:
                    raise AssertionError(f"{case_info}: tool_calling #{tc_idx} missing '{required_field}'")

            tool_name = tc["tool_name"]
            arguments = tc["arguments"]

            if tool_name == "retrieve_plant_graph":
                if isinstance(arguments, dict) and "query_type" in arguments:
                    observed_query_types.append(arguments["query_type"])
                elif isinstance(arguments, str):
                    try:
                        parsed_args = json.loads(arguments)
                        if isinstance(parsed_args, dict) and "query_type" in parsed_args:
                            observed_query_types.append(parsed_args["query_type"])
                    except Exception:
                        pass

            if tool_name == "task":
                if isinstance(arguments, dict) and "subagent_type" in arguments:
                    observed_subagents.append(arguments["subagent_type"])

        # 6. Check reasoning details and consistency
        reasoning_query_types: list[str] = []
        for r_idx, r in enumerate(reasoning, 1):
            for required_field in ["step", "agent", "phase", "thought", "decision", "status"]:
                if required_field not in r:
                    raise AssertionError(f"{case_info}: reasoning #{r_idx} missing '{required_field}'")

            phase = r["phase"]
            thought = r["thought"]
            decision = r["decision"]

            if phase == "graph_query_selection":
                for qtype in [
                    "GET_PHYTOCHEMICALS",
                    "GET_THERAPEUTIC_USES",
                    "GET_BIOACTIVITY",
                    "GET_PLANT_DETAILS",
                    "GET_PLANT_PARTS",
                    "GET_PROTEIN_TARGETS",
                ]:
                    if qtype in thought or qtype in decision:
                        reasoning_query_types.append(qtype)

            if phase == "delegation_decision" and "'specialist'" in decision:
                raise AssertionError(
                    f"{case_info}: Reasoning step {r_idx} uses generic 'specialist' instead of actual subagent name"
                )

        if observed_query_types and reasoning_query_types:
            for obs_qt, reas_qt in zip(observed_query_types, reasoning_query_types):
                if obs_qt != reas_qt:
                    raise AssertionError(
                        f"{case_info}: Query type discrepancy! Tool called '{obs_qt}', but reasoning recorded '{reas_qt}'"
                    )

        # 7. Check routing transitions & timestamps
        routing_timestamps: list[datetime] = []
        for rt_idx, rt in enumerate(routing, 1):
            for required_field in ["step", "routing_type", "decision", "timestamp"]:
                if required_field not in rt:
                    raise AssertionError(f"{case_info}: routing #{rt_idx} missing '{required_field}'")

            ts_str = rt["timestamp"]
            try:
                dt = parse_iso(ts_str)
                routing_timestamps.append(dt)
            except Exception as e:
                raise AssertionError(f"{case_info}: routing #{rt_idx} has invalid ISO timestamp '{ts_str}': {e}")

            if rt["routing_type"] == "subagent_delegation":
                subagent_target = rt.get("to_subagent")
                if subagent_target == "specialist":
                    raise AssertionError(
                        f"{case_info}: routing step {rt_idx} delegates to generic 'specialist' instead of actual subagent"
                    )

        # Monotonicity check on routing timestamps
        for i in range(1, len(routing_timestamps)):
            if routing_timestamps[i] < routing_timestamps[i - 1]:
                raise AssertionError(
                    f"{case_info}: Routing timestamp out of chronological order at step {i+1}! "
                    f"Step {i} was {routing_timestamps[i-1]}, but Step {i+1} is {routing_timestamps[i]}"
                )

        # 8. Check question-specific domains for successful runs
        if not is_error_response:
            q_lower = question.lower()
            if "phytochemical" in q_lower or "chemical compounds" in q_lower:
                if "phytochemical_name" not in identifier:
                    raise AssertionError(f"{case_info}: Phytochemical question must have 'phytochemical_name' in identifier")
                if observed_query_types and observed_query_types[0] != "GET_PHYTOCHEMICALS":
                    raise AssertionError(
                        f"{case_info}: Phytochemical question expected 'GET_PHYTOCHEMICALS', got '{observed_query_types[0]}'"
                    )

            elif "therapeutic" in q_lower or "medicinal uses" in q_lower:
                if "therapeutic_use" not in identifier:
                    raise AssertionError(f"{case_info}: Therapeutic question must have 'therapeutic_use' in identifier")
                if observed_query_types and observed_query_types[0] != "GET_THERAPEUTIC_USES":
                    raise AssertionError(
                        f"{case_info}: Therapeutic question expected 'GET_THERAPEUTIC_USES', got '{observed_query_types[0]}'"
                    )

        status_str = "FAILED_WITH_DIAGNOSTICS" if is_error_response else "PASSED"
        validation_report["cases_validated"].append({
            "record_index": idx,
            "plant_name": plant_name,
            "question": question[:60] + "...",
            "identifier": identifier,
            "query_type": observed_query_types[0] if observed_query_types else "NONE",
            "subagent": observed_subagents[0] if observed_subagents else "NONE",
            "tool_calls_count": len(tool_calling),
            "reasoning_steps": len(reasoning),
            "routing_steps": len(routing),
            "timeline_events": len(timeline),
            "response_length": len(response),
            "status": status_str,
        })

    return validation_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate IMPARK evaluation JSONL output.")
    parser.add_argument(
        "file",
        type=Path,
        nargs="?",
        default=Path("data/verified_eval.jsonl"),
        help="Path to JSONL file to validate",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail validation if any record contains an execution error response",
    )
    args = parser.parse_args()

    print(f"Validating evaluation file: {args.file}")
    try:
        report = validate_evaluation_file(args.file, strict_no_errors=args.strict)
        print(f"\n[SUCCESS] {report['total_records']} records validated in {args.file}")
        print(f"  Successful: {report['successful_records']} | Failed: {report['failed_records']}")
        for case in report["cases_validated"]:
            print(f"  Record #{case['record_index']}: Plant='{case['plant_name']}'")
            print(f"    Question: {case['question']}")
            print(f"    Identifier: {case['identifier']}")
            print(f"    Tool Query: {case['query_type']} | Subagent: {case['subagent']}")
            print(f"    Steps: Tools={case['tool_calls_count']}, Reasoning={case['reasoning_steps']}, Routing={case['routing_steps']}")
            print(f"    Status: {case['status']}\n")
        sys.exit(0)
    except AssertionError as ae:
        print(f"\n[VALIDATION FAILED] {ae}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
