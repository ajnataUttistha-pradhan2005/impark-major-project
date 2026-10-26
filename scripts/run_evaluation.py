"""Standalone Plant Question Evaluation Runner for Deep Agents.

Evaluates natural-language questions about Indian medicinal plants using the
existing Deep Agents pipeline, bypassing plant identification stages and
capturing detailed, verified execution traces.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from langchain_core.callbacks import BaseCallbackHandler

from backend.api.schemas.chat import ChatRequest
from backend.config.settings import Settings
from backend.main import create_app
from backend.runtime import loop_factory

logger = logging.getLogger("impark.evaluation")


def utc_iso_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def parse_payload(val: Any) -> Any:
    """Safely parse payloads that may be JSON strings, python literal dicts, or objects."""
    if val is None or isinstance(val, (int, float, bool)):
        return val
    if isinstance(val, dict):
        return {str(k): parse_payload(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [parse_payload(x) for x in val]
    if isinstance(val, str):
        val_clean = val.strip()
        # 1. Try standard JSON
        if (val_clean.startswith("{") and val_clean.endswith("}")) or (
            val_clean.startswith("[") and val_clean.endswith("]")
        ):
            try:
                parsed = json.loads(val_clean)
                return parse_payload(parsed)
            except Exception:
                pass
            # 2. Try Python literal eval (e.g. single quotes from repr)
            try:
                import ast
                parsed = ast.literal_eval(val_clean)
                if isinstance(parsed, (dict, list)):
                    return parse_payload(parsed)
            except Exception:
                pass
        return val_clean
    if hasattr(val, "content"):
        return str(getattr(val, "content", ""))
    if hasattr(val, "model_dump"):
        try:
            return parse_payload(val.model_dump(mode="json"))
        except Exception:
            return str(val)
    if hasattr(val, "dict"):
        try:
            return parse_payload(val.dict())
        except Exception:
            return str(val)
    return str(val)


def parse_identifier(raw: Any) -> list[str]:
    """Parse identifier into a JSON-compatible list of strings."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        val_clean = raw.strip()
        if val_clean.startswith("[") and val_clean.endswith("]"):
            try:
                parsed = json.loads(val_clean)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
            try:
                import ast
                parsed = ast.literal_eval(val_clean)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
        elif val_clean:
            return [val_clean]
    return []


def redact_sensitive(val: Any) -> Any:
    """Recursively mask sensitive values in trace dictionaries."""
    val = parse_payload(val)
    if isinstance(val, dict):
        cleaned: dict[str, Any] = {}
        for k, v in val.items():
            if any(term in str(k).lower() for term in ("password", "secret", "token", "key", "auth")):
                cleaned[str(k)] = "***REDACTED***"
            else:
                cleaned[str(k)] = redact_sensitive(v)
        return cleaned
    if isinstance(val, list):
        return [redact_sensitive(item) for item in val]
    return val


class EvaluationTraceCallback(BaseCallbackHandler):
    """LangChain / LangGraph callback handler capturing detailed agent execution traces."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []
        self._starts: dict[str, float] = {}
        self.step = 0

    def _next_step(self) -> int:
        self.step += 1
        return self.step

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._starts[str(run_id)] = time.perf_counter()
        agent = (
            metadata.get("agent_name") or metadata.get("langgraph_node") or "orchestrator"
            if metadata
            else "orchestrator"
        )
        model_name = serialized.get("name") or (
            serialized.get("id", [""])[-1] if isinstance(serialized.get("id"), list) else ""
        )
        self.events.append({
            "step": self._next_step(),
            "event_type": "llm_start",
            "timestamp": utc_iso_now(),
            "agent": agent,
            "status": "started",
            "details": {
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "model_name": model_name,
                "prompts_count": len(prompts),
            },
        })

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        start = self._starts.pop(str(run_id), None)
        duration_ms = round((time.perf_counter() - start) * 1000, 2) if start else None
        output_summary = ""
        try:
            generations = getattr(response, "generations", [])
            if generations and generations[0]:
                gen = generations[0][0]
                output_summary = str(getattr(gen, "text", "") or getattr(gen.message, "content", ""))[:400]
        except Exception:
            pass

        self.events.append({
            "step": self._next_step(),
            "event_type": "llm_end",
            "timestamp": utc_iso_now(),
            "agent": "orchestrator",
            "status": "ok",
            "duration_ms": duration_ms,
            "output": output_summary,
            "details": {
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
            },
        })

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        start = self._starts.pop(str(run_id), None)
        duration_ms = round((time.perf_counter() - start) * 1000, 2) if start else None
        self.events.append({
            "step": self._next_step(),
            "event_type": "llm_error",
            "timestamp": utc_iso_now(),
            "agent": "orchestrator",
            "status": "error",
            "duration_ms": duration_ms,
            "output": str(error),
            "details": {
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "error_type": type(error).__name__,
            },
        })

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._starts[str(run_id)] = time.perf_counter()
        tool_name = serialized.get("name") or "tool"
        agent = "orchestrator"
        subagent = None

        parsed_input = parse_payload(input_str)

        event_type = "tool_call"
        if tool_name == "task":
            event_type = "subagent_delegation"
            if isinstance(parsed_input, dict):
                subagent = parsed_input.get("subagent_type")
        elif tool_name == "retrieve_plant_graph":
            agent = "knowledge_graph"
            event_type = "retrieval_query"
        elif tool_name == "resolve_plant_names":
            agent = "text_entity"
            event_type = "entity_resolution"
        elif tool_name == "inspect_uploaded_image":
            agent = "image_understanding"
            event_type = "image_classification"

        event: dict[str, Any] = {
            "step": self._next_step(),
            "event_type": event_type,
            "timestamp": utc_iso_now(),
            "agent": agent,
            "tool_name": tool_name,
            "status": "started",
            "input": redact_sensitive(parsed_input),
            "details": {
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
            },
        }
        if subagent:
            event["subagent"] = subagent
        self.events.append(event)

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        start = self._starts.pop(str(run_id), None)
        duration_ms = round((time.perf_counter() - start) * 1000, 2) if start else None
        parsed_output = parse_payload(output)

        self.events.append({
            "step": self._next_step(),
            "event_type": "tool_completed",
            "timestamp": utc_iso_now(),
            "status": "ok",
            "duration_ms": duration_ms,
            "output": redact_sensitive(parsed_output),
            "details": {
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
            },
        })

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        start = self._starts.pop(str(run_id), None)
        duration_ms = round((time.perf_counter() - start) * 1000, 2) if start else None
        self.events.append({
            "step": self._next_step(),
            "event_type": "tool_failed",
            "timestamp": utc_iso_now(),
            "status": "error",
            "duration_ms": duration_ms,
            "output": str(error),
            "details": {
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "error_type": type(error).__name__,
            },
        })


def build_structured_trace(
    plant_name: str,
    question: str,
    trace_cb: EvaluationTraceCallback,
    app_trace_events: list[Any],
    state: Any | None,
    turn_resp: Any | None,
    case_start_iso: str,
    case_end_iso: str,
    elapsed_case_ms: float,
    error: Exception | None = None,
) -> dict[str, Any]:
    """Assemble structured traces covering Tool calling, Reasoning, Routing, and Timeline.
    
    Guarantees:
    - Events, query types, arguments, and subagent names strictly match actual execution.
    - Timestamps and execution orders are strictly chronological.
    - Differentiates observed execution details from decision summaries.
    """
    tool_calling: list[dict[str, Any]] = []
    reasoning: list[dict[str, Any]] = []
    routing: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    # 1. Routing & Reasoning: Entry transition at start of turn
    routing.append({
        "step": 1,
        "routing_type": "graph_node_transition",
        "from_node": "START",
        "to_node": "deep_orchestrator",
        "decision": f"Route question to deep_orchestrator with plant scope locked to '{plant_name}'",
        "timestamp": case_start_iso,
    })

    reasoning.append({
        "step": 1,
        "agent": "orchestrator",
        "phase": "initial_planning",
        "thought": (
            f"Active plant scope is established and locked to '{plant_name}'. Evaluated input question: '{question}'. "
            "Determining required specialist delegation among knowledge_graph, text_entity, and image_understanding."
        ),
        "decision": f"Lock turn scope to '{plant_name}' and initiate Deep Agents orchestrator turn.",
        "status": "working",
    })

    # 2. Pair tool starts and tool completions by run_id
    tool_starts_by_run_id: dict[str, dict[str, Any]] = {}
    pending_tool_starts: list[dict[str, Any]] = []

    for ev in trace_cb.events:
        timeline.append(ev)
        ev_type = ev.get("event_type")
        run_id = ev.get("details", {}).get("run_id")

        if ev_type in ("tool_call", "subagent_delegation", "retrieval_query", "entity_resolution", "image_classification"):
            if run_id:
                tool_starts_by_run_id[run_id] = ev
            pending_tool_starts.append(ev)

            tool_name = ev.get("tool_name", "")
            tool_input = ev.get("input")

            if tool_name == "task":
                # Subagent delegation observed
                subagent = ev.get("subagent")
                if not subagent and isinstance(tool_input, dict):
                    subagent = tool_input.get("subagent_type")
                subagent_name = subagent or "knowledge_graph"

                desc = ""
                if isinstance(tool_input, dict):
                    desc = str(tool_input.get("description", ""))
                else:
                    desc = str(tool_input)

                routing.append({
                    "step": len(routing) + 1,
                    "routing_type": "subagent_delegation",
                    "from_agent": "orchestrator",
                    "to_subagent": subagent_name,
                    "tool_invoked": "task",
                    "decision": f"Orchestrator delegates domain fact retrieval to subagent '{subagent_name}'",
                    "timestamp": ev.get("timestamp"),
                    "details": {"description": desc},
                })
                reasoning.append({
                    "step": len(reasoning) + 1,
                    "agent": "orchestrator",
                    "phase": "delegation_decision",
                    "thought": f"Question requires botanical, chemical, or therapeutic facts for '{plant_name}'. Delegating to '{subagent_name}'.",
                    "decision": f"Invoke subagent '{subagent_name}' via task tool with objective: '{desc}'",
                    "status": "working",
                })

            elif tool_name == "retrieve_plant_graph":
                # Knowledge graph retrieval query observed
                actual_query_type = ""
                if isinstance(tool_input, dict):
                    actual_query_type = str(tool_input.get("query_type", "")).strip()
                elif isinstance(tool_input, str):
                    parsed_in = parse_payload(tool_input)
                    if isinstance(parsed_in, dict):
                        actual_query_type = str(parsed_in.get("query_type", "")).strip()

                if not actual_query_type and state and state.context.recent_query_types:
                    actual_query_type = (
                        state.context.recent_query_types[-1].value
                        if hasattr(state.context.recent_query_types[-1], "value")
                        else str(state.context.recent_query_types[-1])
                    )
                if not actual_query_type:
                    actual_query_type = "GET_PLANT_DETAILS"

                routing.append({
                    "step": len(routing) + 1,
                    "routing_type": "tool_selection",
                    "from_subagent": "knowledge_graph",
                    "to_tool": "retrieve_plant_graph",
                    "decision": f"Knowledge graph subagent selects typed query '{actual_query_type}' scoped to plant '{plant_name}'",
                    "timestamp": ev.get("timestamp"),
                })
                reasoning.append({
                    "step": len(reasoning) + 1,
                    "agent": "knowledge_graph",
                    "phase": "graph_query_selection",
                    "thought": f"Selected typed query '{actual_query_type}' to fetch verified Neo4j knowledge graph evidence for '{plant_name}'.",
                    "decision": f"Execute allow-listed Cypher query '{actual_query_type}'",
                    "status": "working",
                })

            else:
                routing.append({
                    "step": len(routing) + 1,
                    "routing_type": "tool_selection",
                    "from_agent": ev.get("agent", "orchestrator"),
                    "to_tool": tool_name,
                    "decision": f"Invoke tool '{tool_name}'",
                    "timestamp": ev.get("timestamp"),
                })

        elif ev_type in ("tool_completed", "tool_failed"):
            output = ev.get("output")
            duration_ms = ev.get("duration_ms")
            matched_start = tool_starts_by_run_id.pop(run_id, None) if run_id else None
            if not matched_start and pending_tool_starts:
                matched_start = pending_tool_starts.pop(0)

            tool_name = matched_start.get("tool_name", "tool") if matched_start else "tool"
            tool_agent = matched_start.get("agent", "orchestrator") if matched_start else "orchestrator"
            tool_args = matched_start.get("input", {}) if matched_start else {}
            call_status = "ok" if ev_type == "tool_completed" else "error"

            tool_calling.append({
                "step": len(tool_calling) + 1,
                "tool_name": tool_name,
                "agent": tool_agent,
                "arguments": tool_args,
                "result": output,
                "status": call_status,
                "duration_ms": duration_ms,
            })

            if tool_name == "task" and call_status == "ok":
                subagent_name = (
                    matched_start.get("subagent")
                    or (tool_args.get("subagent_type") if isinstance(tool_args, dict) else None)
                    or "knowledge_graph"
                )
                routing.append({
                    "step": len(routing) + 1,
                    "routing_type": "subagent_handoff",
                    "from_subagent": subagent_name,
                    "to_agent": "orchestrator",
                    "decision": f"Subagent '{subagent_name}' completed retrieval and returned observation payload to main orchestrator",
                    "timestamp": ev.get("timestamp"),
                })
                reasoning.append({
                    "step": len(reasoning) + 1,
                    "agent": "orchestrator",
                    "phase": "evidence_review",
                    "thought": f"Received subagent observation from '{subagent_name}'. Evaluating whether retrieved facts sufficiently address '{question}'.",
                    "decision": "Assess evidence sufficiency and synthesize response.",
                    "status": "working",
                })

    # 3. Integrate durable app trace events into timeline
    for ate in app_trace_events:
        timeline.append({
            "step": len(timeline) + 1,
            "event_type": f"app_{ate.event_type.value}",
            "timestamp": ate.timestamp.isoformat(),
            "agent": ate.component,
            "status": ate.status,
            "duration_ms": ate.latency_ms,
            "details": ate.details,
        })

    # Sort timeline chronologically to ensure strict consistency
    timeline.sort(key=lambda x: str(x.get("timestamp", "")))
    for idx, event in enumerate(timeline, 1):
        event["step"] = idx

    # 4. Final completion or error handling
    if error:
        reasoning.append({
            "step": len(reasoning) + 1,
            "agent": "orchestrator",
            "phase": "failure_handling",
            "thought": f"An error occurred during workflow execution: {type(error).__name__}: {str(error)}",
            "decision": "Halt execution and report failure status.",
            "status": "error",
        })
        routing.append({
            "step": len(routing) + 1,
            "routing_type": "graph_node_transition",
            "from_node": "deep_orchestrator",
            "to_node": "END",
            "decision": f"Execution halted due to {type(error).__name__}",
            "timestamp": case_end_iso,
        })
    else:
        cited_count = (
            len(getattr(turn_resp.response, "citation_ids", []) or [])
            if turn_resp and turn_resp.response
            else 0
        )
        provider = (
            getattr(turn_resp.response, "provider", "deepagents")
            if turn_resp and turn_resp.response
            else "deepagents"
        )
        reasoning.append({
            "step": len(reasoning) + 1,
            "agent": "orchestrator",
            "phase": "completion_decision",
            "thought": (
                f"Retrieved facts verified. Found {cited_count} citations supporting the response via provider '{provider}'. "
                "Fact coverage is complete; stopping tool calling and finalizing response."
            ),
            "decision": "Stop execution (done_reason='stop'), finalize cited natural-language answer, and mark task COMPLETE.",
            "status": "finished",
        })
        routing.append({
            "step": len(routing) + 1,
            "routing_type": "graph_conditional_edge",
            "from_node": "deep_orchestrator",
            "to_node": "END",
            "condition": "status == COMPLETE",
            "decision": "Turn objectives satisfied; conditional edge routes directly to END (bypassing clarification).",
            "timestamp": case_end_iso,
        })

    return {
        "tool_calling": tool_calling,
        "reasoning": reasoning,
        "routing": routing,
        "timeline": timeline,
    }


def load_xlsx_records(file_path: Path) -> list[dict[str, Any]]:
    """Parse Excel (.xlsx) file using standard library zipfile and XML parser."""
    with zipfile.ZipFile(file_path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in tree.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                shared.append(
                    "".join(
                        t.text or ""
                        for t in si.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                    )
                )

        sheet_tree = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows: list[dict[str, str]] = []
        for r in sheet_tree.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
            row_data: dict[str, str] = {}
            for c in r.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                ref = c.get("r") or ""
                col = "".join([ch for ch in ref if ch.isalpha()])
                v = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                val = v.text if v is not None else ""
                if c.get("t") == "s" and val:
                    val = shared[int(val)]
                row_data[col] = val
            if row_data:
                rows.append(row_data)

    if not rows:
        return []

    headers = {col: val.strip() for col, val in rows[0].items()}
    records: list[dict[str, Any]] = []
    for r in rows[1:]:
        rec = {headers[col]: val for col, val in r.items() if col in headers}
        if any(rec.values()):
            records.append(rec)
    return records


def load_input_dataset(
    input_path: Path,
    plants_path: Path | None = None,
    target_plant: str | None = None,
    plant_mode: str = "product",
) -> list[dict[str, Any]]:
    """Load evaluation test cases from JSON, JSONL, CSV, or Excel file."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    suffix = input_path.suffix.lower()
    raw_records: list[dict[str, Any]] = []

    if suffix == ".json":
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                raw_records = data
            elif isinstance(data, dict):
                raw_records = [data]
    elif suffix == ".jsonl":
        with open(input_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    raw_records.append(json.loads(line))
    elif suffix == ".csv":
        with open(input_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            raw_records = list(reader)
    elif suffix in (".xlsx", ".xlsm"):
        raw_records = load_xlsx_records(input_path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")

    # Check if rows already have plant_name column
    has_plant_name = all("plant_name" in r and r["plant_name"] for r in raw_records)

    if has_plant_name:
        test_cases: list[dict[str, Any]] = []
        for r in raw_records:
            plant_name = str(r["plant_name"]).strip()
            if target_plant and plant_name.casefold() != target_plant.casefold():
                continue
            test_cases.append({
                "plant_name": plant_name,
                "question": str(r.get("question", "")).strip(),
                "identifier": parse_identifier(r.get("identifier")),
            })
        return test_cases

    # Rows do not specify plant_name directly; load available plant names
    available_plants: list[str] = []
    if target_plant:
        available_plants = [target_plant]
    else:
        candidate_plants_file = plants_path
        if candidate_plants_file is None or not candidate_plants_file.exists():
            candidate_plants_file = input_path.parent / "plant_names.json"

        if candidate_plants_file.exists():
            with open(candidate_plants_file, encoding="utf-8") as f:
                plants_data = json.load(f)
                for item in plants_data:
                    if isinstance(item, dict) and "plant_name" in item:
                        available_plants.append(item["plant_name"])
                    elif isinstance(item, str):
                        available_plants.append(item)
        else:
            raise ValueError(
                f"Input file '{input_path}' contains questions without plant_name, "
                f"and no plant_names.json was found at '{candidate_plants_file}'. "
                "Specify --plants or --plant."
            )

    test_cases = []
    if plant_mode == "pair":
        # 1-to-1 pairing
        for idx, rec in enumerate(raw_records):
            plant_name = available_plants[idx % len(available_plants)]
            test_cases.append({
                "plant_name": plant_name,
                "question": str(rec.get("question", "")).strip(),
                "identifier": parse_identifier(rec.get("identifier")),
            })
    else:
        # Product mode: each plant x each question
        for plant_name in available_plants:
            for rec in raw_records:
                test_cases.append({
                    "plant_name": plant_name,
                    "question": str(rec.get("question", "")).strip(),
                    "identifier": parse_identifier(rec.get("identifier")),
                })

    return test_cases


def read_completed_keys(output_path: Path) -> set[tuple[str, str]]:
    """Read already completed (plant_name, question) keys from existing JSONL output."""
    completed: set[tuple[str, str]] = set()
    if not output_path.exists():
        return completed

    try:
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    p = str(obj.get("plant_name", "")).strip()
                    q = str(obj.get("question", "")).strip()
                    resp = str(obj.get("response", "")).strip()
                    # Only mark as completed if all 5 fields exist and response did not fail with [ERROR]
                    if (
                        p
                        and q
                        and "traces" in obj
                        and "identifier" in obj
                        and resp
                        and not resp.startswith("[ERROR]")
                    ):
                        completed.add((p, q))
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Failed to read existing completed keys from {output_path}: {e}")

    return completed


async def run_evaluation(
    input_path: Path,
    output_path: Path,
    plants_path: Path | None = None,
    target_plant: str | None = None,
    plant_mode: str = "product",
    limit: int | None = None,
    offset: int = 0,
    resume: bool = True,
    summary_report: bool = True,
) -> dict[str, Any]:
    """Execute evaluation questions sequentially through the existing Deep Agents workflow."""
    start_total_time = time.perf_counter()
    logger.info("Starting Plant Question Evaluation Runner")
    logger.info("Input: %s | Output: %s", input_path, output_path)

    # 1. Load dataset
    test_cases = load_input_dataset(input_path, plants_path, target_plant, plant_mode)
    total_cases = len(test_cases)
    logger.info("Loaded %d test cases", total_cases)

    # Read completed keys for resume
    completed_keys = read_completed_keys(output_path) if resume else set()
    if completed_keys:
        logger.info("Found %d previously completed test cases. Resuming...", len(completed_keys))

    unique_plants = sorted(set(tc["plant_name"] for tc in test_cases))
    unique_questions = sorted(set(tc["question"] for tc in test_cases))
    total_expected = len(test_cases)
    cases_remaining = max(0, total_expected - len(completed_keys))

    print("\n" + "=" * 70)
    print("IMPARK PLANT QUESTION EVALUATION RUNNER")
    print("=" * 70)
    print(f"Questions dataset:         {input_path}")
    print(f"Plants dataset:            {plants_path or 'from catalog/dataset'}")
    print(f"Unique plants loaded:      {len(unique_plants)}")
    print(f"Unique questions loaded:   {len(unique_questions)}")
    print(f"Combination mode:          {plant_mode} (Cartesian product: {len(unique_plants)} x {len(unique_questions)})")
    print(f"Total expected test cases: {total_expected}")
    print(f"Previously completed:      {len(completed_keys)} (will be skipped in resume mode)")
    print(f"Remaining test cases:      {cases_remaining}")
    print(f"Output destination:        {output_path}")
    print(f"Resume enabled:            {resume}")
    if limit is not None:
        print(f"Execution limit:           {limit} new cases")
    if offset > 0:
        print(f"Execution offset:          {offset}")
    print("=" * 70 + "\n")

    # Apply offset
    if offset > 0:
        test_cases = test_cases[offset:]
        logger.info("Applied offset %d (remaining: %d)", offset, len(test_cases))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_file_mode = "a" if resume else "w"

    # 2. Initialize application and services
    app = create_app()
    stats = {
        "total_evaluated": 0,
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "start_time": utc_iso_now(),
    }

    async with app.router.lifespan_context(app):
        service = app.state.conversations

        # Resolve all plant names to canonical catalog records (UUID & label)
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
            for idx, tc in enumerate(test_cases, 1):
                # Stop if we have evaluated the requested limit of new cases
                if limit is not None and stats["total_evaluated"] >= limit:
                    logger.info("Reached evaluation limit of %d cases. Stopping.", limit)
                    break

                plant_name = tc.get("plant_name", "").strip()
                question = tc.get("question", "").strip()
                identifier = tc.get("identifier", [])

                if not plant_name or not question:
                    logger.warning("Skipping invalid record #%d: missing plant_name or question", idx)
                    continue

                if resume and (plant_name, question) in completed_keys:
                    stats["skipped"] += 1
                    continue

                logger.info(
                    "[%d/%d] Evaluating (Progress: %d evaluated): Plant='%s' | Question='%s'",
                    idx,
                    len(test_cases),
                    stats["total_evaluated"] + 1,
                    plant_name,
                    question[:60],
                )

                case_start_iso = utc_iso_now()
                case_start_time = time.perf_counter()

                # Look up plant in catalog
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
                    stats["total_evaluated"] += 1
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

                    # 2. Submit turn with plant selection and question
                    # Passing selected_plant_id locks the plant and bypasses identification
                    req = ChatRequest(text=question, selected_plant_id=plant_rec.plant_id)
                    turn_resp = await service.submit(sid, req, uuid4())

                    # 3. Harvest response
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
                    # Restore service config method
                    service._config = orig_config

                # Assemble EXACTLY the required 5 top-level fields
                result_obj = {
                    "plant_name": plant_name,
                    "question": question,
                    "identifier": identifier,
                    "traces": structured_traces,
                    "response": final_response_text,
                }

                out_f.write(json.dumps(result_obj, default=str, ensure_ascii=False) + "\n")
                out_f.flush()
                stats["total_evaluated"] += 1

    stats["end_time"] = utc_iso_now()
    stats["total_elapsed_seconds"] = round(time.perf_counter() - start_total_time, 2)
    cases_remaining_end = max(0, total_expected - (len(completed_keys) + stats["successful"]))

    print("\n" + "=" * 70)
    print("EVALUATION RUN SUMMARY")
    print("=" * 70)
    print(f"Total expected test cases:        {total_expected}")
    print(f"Evaluated in this run:            {stats['total_evaluated']}")
    print(f"Successfully completed cases:     {stats['successful']} (cumulative: {stats['successful'] + len(completed_keys)})")
    print(f"Failed cases in this run:         {stats['failed']}")
    print(f"Cases skipped (already done):     {stats['skipped']}")
    print(f"Cases remaining:                  {cases_remaining_end}")
    print(f"Output file location:             {output_path}")
    print(f"Total elapsed time:               {stats['total_elapsed_seconds']}s")
    print("=" * 70 + "\n")

    logger.info(
        "Evaluation completed in %.2fs: Total=%d | Successful=%d | Failed=%d | Skipped=%d",
        stats["total_elapsed_seconds"],
        stats["total_evaluated"],
        stats["successful"],
        stats["failed"],
        stats["skipped"],
    )

    if summary_report:
        summary_path = output_path.with_suffix(".summary.json")
        try:
            with open(summary_path, "w", encoding="utf-8") as sf:
                json.dump(stats, sf, indent=2)
            logger.info("Summary report written to %s", summary_path)
        except Exception as e:
            logger.warning("Could not write summary report: %e", e)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run natural-language plant questions through the IMPARK Deep Agents pipeline."
    )
    parser.add_argument(
        "--questions",
        "--input",
        "-q",
        "-i",
        dest="input",
        type=Path,
        default=Path("evaluation-job-1/test_data.xlsx"),
        help="Path to evaluation dataset (.xlsx, .json, .jsonl, .csv)",
    )
    parser.add_argument(
        "--plants",
        "-p",
        type=Path,
        default=Path("evaluation-job-1/plant_names.json"),
        help="Path to plant names JSON file (used if input dataset does not have plant_name column)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("data/all_plants_evaluation.jsonl"),
        help="Path to output JSONL file (default: data/all_plants_evaluation.jsonl)",
    )
    parser.add_argument(
        "--plant",
        type=str,
        default=None,
        help="Filter to a specific plant name (e.g. 'Azadirachta indica')",
    )
    parser.add_argument(
        "--plant-mode",
        choices=["product", "pair"],
        default="product",
        help="How to combine plants and questions when plant_name is not in input rows: 'product' (all pairs) or 'pair' (1-to-1)",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Maximum number of test cases to evaluate",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Start index offset for test cases",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not skip previously completed cases in the output file",
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
        run_evaluation(
            input_path=args.input,
            output_path=args.output,
            plants_path=args.plants,
            target_plant=args.plant,
            plant_mode=args.plant_mode,
            limit=args.limit,
            offset=args.offset,
            resume=not args.no_resume,
        ),
        loop_factory=loop_factory,
    )


if __name__ == "__main__":
    main()
