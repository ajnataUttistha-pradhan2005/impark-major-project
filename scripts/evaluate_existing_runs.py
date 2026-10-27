"""Metric Evaluation Pipeline for Existing IMPARK Evaluation Runs.

Evaluates Graph Precision, Groundedness, Traceability, and Trace Completeness
from existing evaluation JSONL records against verified Neo4j ground truth.
Does NOT rerun the agent, call external models, or overwrite previous evaluations.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("impark.evaluation")


def utc_iso_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def normalize_text(text: str | None) -> str:
    """Safe textual normalization for comparison."""
    if text is None:
        return ""
    s = text.strip()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\s+", " ", s)
    return s


def slugify(text: str) -> str:
    """Create a clean alphanumeric slug."""
    s = normalize_text(text).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def normalize_key(val: Any) -> str:
    """Normalize identifiers, keys, or names for safe set membership."""
    if val is None:
        return ""
    s = str(val).strip().lower()
    s = s.replace("-", "").replace("_", "").replace(" ", "")
    return s


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ClaimAnnotation:
    claim_id: str
    test_case_id: str
    plant_name: str
    question_id: str
    answer_claim: str
    cited_evidence_ids: list[str] = field(default_factory=list)
    supporting_retrieved_fact_ids: list[str] = field(default_factory=list)
    support_status: str = "SUPPORTED"  # SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, CONTRADICTED, NOT_VERIFIABLE
    is_traceable: bool = False
    reviewer_notes: str = ""

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "test_case_id": self.test_case_id,
            "plant_name": self.plant_name,
            "question_id": self.question_id,
            "answer_claim": self.answer_claim,
            "cited_evidence_ids": "; ".join(self.cited_evidence_ids),
            "supporting_retrieved_fact_ids": "; ".join(self.supporting_retrieved_fact_ids),
            "support_status": self.support_status,
            "is_traceable": self.is_traceable,
            "reviewer_notes": self.reviewer_notes,
        }


@dataclass
class CaseMetricResult:
    test_case_id: str
    plant_name: str
    question_id: str
    question: str
    ground_truth_status: str
    expected_fact_count: int
    retrieved_fact_count: int
    relevant_retrieved_fact_count: int
    graph_precision: float | str  # float or "N/A"
    factual_claim_count: int
    supported_claim_count: int
    groundedness: float | str  # float or "N/A"
    traceable_claim_count: int
    traceability: float | str  # float or "N/A"
    trace_completeness: float
    review_notes: str = ""

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "test_case_id": self.test_case_id,
            "plant_name": self.plant_name,
            "question_id": self.question_id,
            "question": self.question,
            "ground_truth_status": self.ground_truth_status,
            "expected_fact_count": self.expected_fact_count,
            "retrieved_fact_count": self.retrieved_fact_count,
            "relevant_retrieved_fact_count": self.relevant_retrieved_fact_count,
            "graph_precision": self.graph_precision if isinstance(self.graph_precision, str) else round(self.graph_precision, 4),
            "factual_claim_count": self.factual_claim_count,
            "supported_claim_count": self.supported_claim_count,
            "groundedness": self.groundedness if isinstance(self.groundedness, str) else round(self.groundedness, 4),
            "traceable_claim_count": self.traceable_claim_count,
            "traceability": self.traceability if isinstance(self.traceability, str) else round(self.traceability, 4),
            "trace_completeness": round(self.trace_completeness, 4),
            "review_notes": self.review_notes,
        }


# ============================================================================
# Evaluator Engine
# ============================================================================

class RunEvaluator:
    """Evaluates existing execution runs against verified ground truth."""

    def __init__(self, ground_truth_cases: dict[str, dict[str, Any]]) -> None:
        self.gt_cases = ground_truth_cases

    def evaluate_case(
        self,
        eval_record: dict[str, Any],
        gt_case: dict[str, Any],
    ) -> tuple[CaseMetricResult, list[ClaimAnnotation]]:
        """Evaluate a single test case run against ground truth."""
        test_case_id = gt_case["test_case_id"]
        plant_name = gt_case["plant_name"]
        question_id = gt_case["question_id"]
        question = gt_case["question"]
        gt_status = gt_case["ground_truth_status"]
        expected_facts = gt_case.get("expected_facts", [])

        # 1. Parse retrieved graph facts from traces
        retrieved_facts = self._extract_retrieved_graph_facts(eval_record)
        retrieved_count = len(retrieved_facts)

        # 2. Compute Graph Precision
        relevant_count = 0
        if retrieved_count > 0:
            relevant_count = self._count_relevant_retrieved_facts(
                question_id=question_id,
                question=question,
                retrieved_facts=retrieved_facts,
                expected_facts=expected_facts,
            )
            graph_precision: float | str = relevant_count / retrieved_count
        else:
            graph_precision = "N/A"

        # 3. Extract claims from response
        response_text = str(eval_record.get("response") or "")
        claims = self._extract_claims_from_response(response_text)

        # 4. Evaluate Groundedness & Traceability per claim
        claim_annotations: list[ClaimAnnotation] = []
        supported_claim_count = 0
        traceable_claim_count = 0
        verifiable_claim_count = 0

        for idx, claim_text in enumerate(claims, 1):
            claim_id = f"CLM_{test_case_id}_{idx:02d}"
            annotation = self._evaluate_claim(
                claim_id=claim_id,
                test_case_id=test_case_id,
                plant_name=plant_name,
                question_id=question_id,
                claim_text=claim_text,
                retrieved_facts=retrieved_facts,
            )
            claim_annotations.append(annotation)

            if annotation.support_status != "NOT_VERIFIABLE":
                verifiable_claim_count += 1
                if annotation.support_status == "SUPPORTED":
                    supported_claim_count += 1
                if annotation.is_traceable:
                    traceable_claim_count += 1

        if verifiable_claim_count > 0:
            groundedness: float | str = supported_claim_count / verifiable_claim_count
            traceability: float | str = traceable_claim_count / verifiable_claim_count
        else:
            groundedness = "N/A"
            traceability = "N/A"

        # 5. Compute Trace Completeness
        trace_completeness = self._compute_trace_completeness(eval_record, retrieved_count)

        notes = []
        if retrieved_count == 0:
            notes.append("No graph facts retrieved")
        if question_id == "Q06" and retrieved_count > 0 and relevant_count == 0:
            notes.append("Leaf scope violation: general/other-part facts retrieved for leaf question")
        if verifiable_claim_count == 0:
            notes.append("No verifiable claims in response")

        metric_result = CaseMetricResult(
            test_case_id=test_case_id,
            plant_name=plant_name,
            question_id=question_id,
            question=question,
            ground_truth_status=gt_status,
            expected_fact_count=len(expected_facts),
            retrieved_fact_count=retrieved_count,
            relevant_retrieved_fact_count=relevant_count,
            graph_precision=graph_precision,
            factual_claim_count=verifiable_claim_count,
            supported_claim_count=supported_claim_count,
            groundedness=groundedness,
            traceable_claim_count=traceable_claim_count,
            traceability=traceability,
            trace_completeness=trace_completeness,
            review_notes="; ".join(notes),
        )

        return metric_result, claim_annotations

    def _extract_retrieved_graph_facts(self, eval_record: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract all graph facts retrieved by retrieve_plant_graph calls in the trace."""
        tool_calls = eval_record.get("traces", {}).get("tool_calling", [])
        facts: list[dict[str, Any]] = []

        for call in tool_calls:
            tname = call.get("tool_name") or call.get("name")
            if tname == "retrieve_plant_graph":
                res = call.get("result") or call.get("output")
                if isinstance(res, dict):
                    call_facts = res.get("facts", [])
                    qtype = call.get("arguments", {}).get("query_type")
                    part_id = call.get("arguments", {}).get("part_id")
                    for f in call_facts:
                        if isinstance(f, dict):
                            item = dict(f)
                            item["query_type"] = qtype
                            item["part_id"] = part_id
                            facts.append(item)
        return facts

    def _count_relevant_retrieved_facts(
        self,
        question_id: str,
        question: str,
        retrieved_facts: list[dict[str, Any]],
        expected_facts: list[dict[str, Any]],
    ) -> int:
        """Count how many retrieved facts match the required scope and expected attributes."""
        # Question 6 is leaf-scoped:
        is_leaf_question = (question_id == "Q06" or "leaf" in question.lower() or "leaves" in question.lower())

        # Collect verified ground truth keys for matching
        expected_names: set[str] = set()
        expected_ids: set[str] = set()
        expected_parts: set[str] = set()

        for ef in expected_facts:
            rec = ef.get("record", {})
            val = ef.get("expected_fact", "")
            if val:
                expected_names.add(normalize_key(val))
            for k in ["phytochemical_name", "therapeutic_use", "alias", "plant_part", "target_name", "standard_type"]:
                if k in rec and rec[k]:
                    expected_names.add(normalize_key(rec[k]))
            for k in ["inchi_key", "mesh_id", "uniprot_id", "chembl_id", "bioactivity_id", "plant_part_id"]:
                if k in rec and rec[k]:
                    expected_ids.add(normalize_key(rec[k]))
            if "plant_part" in rec and rec["plant_part"]:
                expected_parts.add(normalize_key(rec["plant_part"]))

        relevant_count = 0
        for rf in retrieved_facts:
            rec = rf.get("record", {})
            qtype = rf.get("query_type")
            part_id = rf.get("part_id")

            # Scope enforcement for leaf question (Q06):
            if is_leaf_question:
                # "A therapeutic use associated with a plant in general must not count as
                # relevant evidence for a leaf-specific question unless the retrieved fact supports that specific scope."
                rec_part = normalize_key(rec.get("plant_part") or part_id or "")
                rec_use = normalize_key(rec.get("therapeutic_use") or "")
                # Only count as relevant if the retrieved record explicitly supports the leaf scope
                if rec_part in ("leaf", "leaves", "baalle") and rec_use in expected_names:
                    relevant_count += 1
                continue

            # Standard attribute matching for other questions:
            matched = False
            # Check ID matches
            for k in ["inchi_key", "mesh_id", "uniprot_id", "chembl_id", "bioactivity_id", "plant_part_id"]:
                if k in rec and normalize_key(rec[k]) in expected_ids:
                    matched = True
                    break
            # Check Name matches
            if not matched:
                for k in ["phytochemical_name", "therapeutic_use", "alias", "plant_part", "target_name"]:
                    if k in rec and normalize_key(rec[k]) in expected_names:
                        matched = True
                        break
            # Check standard_type for bioactivities
            if not matched and question_id in ("Q09", "Q10", "Q11", "Q12") and qtype == "GET_BIOACTIVITY":
                if "bioactivity_id" in rec and rec["bioactivity_id"]:
                    matched = True
            # Documented parts for Q18
            if not matched and question_id == "Q18" and qtype == "GET_PLANT_PARTS":
                matched = True

            if matched:
                relevant_count += 1

        return relevant_count

    def _extract_claims_from_response(self, response_text: str) -> list[str]:
        """Extract individual factual claim statements from markdown response."""
        lines = [line.strip() for line in response_text.split("\n") if line.strip()]
        claims: list[str] = []

        disclaimer_markers = [
            "for learning only", "medical advice", "ask about a specific plant part",
            "more records may be available", "more related information",
            "these are reported associations", "these compounds are part of the plant's secondary metabolism",
            "secondary metabolism, which involves",
        ]

        for line in lines:
            line_lower = line.lower()
            # Skip disclaimers
            if any(marker in line_lower for marker in disclaimer_markers):
                continue

            # Bullet points or list items
            if line.startswith(("*", "-", "+")) or re.match(r"^\d+\.", line):
                # Clean leading list markers
                clean_claim = re.sub(r"^[\*\-\+\d\.\s]+", "", line).strip()
                if len(clean_claim) > 5:
                    claims.append(clean_claim)
            elif ":" in line and not line.endswith(":"):
                # Sub-item like "Bark: Antihypertensive agents [1]"
                claims.append(line)
            elif len(line) > 30 and not line.endswith(":"):
                # Standalone factual sentence
                claims.append(line)

        # Fallback if no bullet points extracted
        if not claims and response_text.strip():
            # Split by period
            sentences = [s.strip() for s in re.split(r"\.\s+", response_text) if len(s.strip()) > 15]
            for s in sentences:
                if not any(marker in s.lower() for marker in disclaimer_markers):
                    claims.append(s)

        return claims

    def _evaluate_claim(
        self,
        claim_id: str,
        test_case_id: str,
        plant_name: str,
        question_id: str,
        claim_text: str,
        retrieved_facts: list[dict[str, Any]],
    ) -> ClaimAnnotation:
        """Determine if a claim is supported by retrieved evidence and traceable to citations."""
        # 1. Extract citation numbers like [1], [2], or UUIDs
        citation_matches = re.findall(r"\[(\d+|[a-f0-9\-]{36})\]", claim_text)
        cited_ids: list[str] = []

        # Map citation indices to retrieved facts
        supporting_fact_ids: list[str] = []
        is_traceable = False

        # Build indexed map of retrieved facts
        # Fact 1 -> index 0, etc.
        resolved_facts_from_citations: list[dict[str, Any]] = []
        for cite in citation_matches:
            cited_ids.append(f"[{cite}]")
            if cite.isdigit():
                idx = int(cite) - 1
                if 0 <= idx < len(retrieved_facts):
                    fact = retrieved_facts[idx]
                    resolved_facts_from_citations.append(fact)
                    fid = fact.get("citation_id") or fact.get("record", {}).get("bioactivity_id") or f"FACT_{idx+1}"
                    supporting_fact_ids.append(str(fid))
            else:
                # UUID citation
                for fact in retrieved_facts:
                    if fact.get("citation_id") == cite:
                        resolved_facts_from_citations.append(fact)
                        supporting_fact_ids.append(cite)

        # Check support status
        claim_lower = claim_text.lower()
        if "no records" in claim_lower or "do not contain" in claim_lower or "not recorded" in claim_lower:
            # Negative claim: supported if query returned 0 facts
            if len(retrieved_facts) == 0:
                support_status = "SUPPORTED"
                is_traceable = False
                notes = "Negative assertion supported by empty retrieval."
            else:
                support_status = "PARTIALLY_SUPPORTED"
                notes = "Negative assertion made despite retrieved records present."
            return ClaimAnnotation(
                claim_id=claim_id,
                test_case_id=test_case_id,
                plant_name=plant_name,
                question_id=question_id,
                answer_claim=claim_text,
                cited_evidence_ids=cited_ids,
                supporting_retrieved_fact_ids=supporting_fact_ids,
                support_status=support_status,
                is_traceable=is_traceable,
                reviewer_notes=notes,
            )

        # Check if the cited fact(s) actually support the claim text
        # Look for keywords/entities from retrieved facts appearing in claim text
        supported_by_citation = False
        for fact in resolved_facts_from_citations:
            rec = fact.get("record", {})
            for key, val in rec.items():
                if val is not None and isinstance(val, (str, int, float)):
                    sval = str(val).strip().lower()
                    if len(sval) >= 3 and sval in claim_lower:
                        supported_by_citation = True
                        break
            if supported_by_citation:
                break

        # Check if any other retrieved fact supports the claim
        supported_by_any = supported_by_citation
        if not supported_by_any:
            for fact in retrieved_facts:
                rec = fact.get("record", {})
                for key, val in rec.items():
                    if val is not None and isinstance(val, (str, int, float)):
                        sval = str(val).strip().lower()
                        if len(sval) >= 3 and sval in claim_lower:
                            supported_by_any = True
                            fid = fact.get("citation_id") or fact.get("record", {}).get("bioactivity_id") or "retrieved_fact"
                            if str(fid) not in supporting_fact_ids:
                                supporting_fact_ids.append(str(fid))
                            break
                if supported_by_any:
                    break

        if supported_by_citation:
            support_status = "SUPPORTED"
            is_traceable = True
            notes = "Claim verified against cited retrieved evidence."
        elif supported_by_any:
            support_status = "SUPPORTED"
            is_traceable = False
            notes = "Claim supported by retrieved evidence but lacks valid direct citation."
        elif len(retrieved_facts) == 0:
            support_status = "UNSUPPORTED"
            is_traceable = False
            notes = "No retrieved evidence exists in this execution to support claim."
        else:
            support_status = "UNSUPPORTED"
            is_traceable = False
            notes = "Entities in claim not found in execution retrieved evidence."

        return ClaimAnnotation(
            claim_id=claim_id,
            test_case_id=test_case_id,
            plant_name=plant_name,
            question_id=question_id,
            answer_claim=claim_text,
            cited_evidence_ids=cited_ids,
            supporting_retrieved_fact_ids=supporting_fact_ids,
            support_status=support_status,
            is_traceable=is_traceable,
            reviewer_notes=notes,
        )

    def _compute_trace_completeness(self, eval_record: dict[str, Any], retrieved_count: int) -> float:
        """Compute trace completeness based on observed pipeline trace events and tool execution."""
        traces = eval_record.get("traces", {})
        timeline = traces.get("timeline", [])
        tool_calling = traces.get("tool_calling", [])

        checks = {
            "session_created": any(e.get("event_type") == "app_session_created" for e in timeline),
            "turn_started": any(e.get("event_type") == "app_turn_started" for e in timeline),
            "tool_called": len(tool_calling) > 0,
            "tool_succeeded": all(c.get("status") in ("ok", None) for c in tool_calling) if tool_calling else False,
            "response_generated": bool(eval_record.get("response")),
        }

        score = sum(1.0 for passed in checks.values() if passed) / len(checks)
        return round(score, 4)


# ============================================================================
# Main Evaluation Workflow and CLI
# ============================================================================

def evaluate_runs(
    ground_truth_path: Path,
    evaluation_jsonl_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Execute evaluation over existing run outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    case_metrics_csv_path = output_dir / "case_metrics.csv"
    claim_annotations_csv_path = output_dir / "claim_annotations.csv"
    aggregate_metrics_json_path = output_dir / "aggregate_metrics.json"
    evaluation_report_json_path = output_dir / "evaluation_report.json"
    unmatched_cases_csv_path = output_dir / "unmatched_cases.csv"

    if not overwrite:
        existing = [p for p in [case_metrics_csv_path, claim_annotations_csv_path, aggregate_metrics_json_path, evaluation_report_json_path] if p.exists()]
        if existing:
            raise FileExistsError(
                f"Output files already exist in {output_dir}: {[p.name for p in existing]}. Pass --overwrite to replace them."
            )

    # 1. Load ground truth cases
    logger.info("Loading ground truth cases from %s ...", ground_truth_path)
    gt_cases: dict[tuple[str, str], dict[str, Any]] = {}
    with open(ground_truth_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                key = (normalize_text(c["plant_name"]).lower(), normalize_text(c["question"]).lower())
                gt_cases[key] = c
    logger.info("Loaded %d ground truth cases.", len(gt_cases))

    # 2. Load existing evaluation records
    logger.info("Loading evaluation JSONL records from %s ...", evaluation_jsonl_path)
    eval_records: list[dict[str, Any]] = []
    with open(evaluation_jsonl_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    eval_records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("Malformed JSON at %s:%d: %s", evaluation_jsonl_path, line_no, e)

    logger.info("Loaded %d evaluation records.", len(eval_records))

    # 3. Match records
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unmatched_eval: list[dict[str, Any]] = []
    seen_gt_keys: set[tuple[str, str]] = set()

    for rec in eval_records:
        p_name = normalize_text(rec.get("plant_name")).lower()
        q_text = normalize_text(rec.get("question")).lower()
        key = (p_name, q_text)

        if key in gt_cases:
            matched_pairs.append((rec, gt_cases[key]))
            seen_gt_keys.add(key)
        else:
            # Try matching by plant and question start substring
            matched = False
            for gt_key, gt_c in gt_cases.items():
                if gt_key[0] == p_name and (gt_key[1][:30] == q_text[:30] or q_text[:30] in gt_key[1]):
                    matched_pairs.append((rec, gt_c))
                    seen_gt_keys.add(gt_key)
                    matched = True
                    break
            if not matched:
                unmatched_eval.append({
                    "reason": "Evaluation record has no matching ground-truth case",
                    "plant_name": rec.get("plant_name"),
                    "question": rec.get("question"),
                })

    unmatched_gt: list[dict[str, Any]] = []
    for gt_key, gt_c in gt_cases.items():
        if gt_key not in seen_gt_keys:
            unmatched_gt.append({
                "reason": "Ground-truth case has no corresponding evaluation record",
                "test_case_id": gt_c.get("test_case_id"),
                "plant_name": gt_c.get("plant_name"),
                "question": gt_c.get("question"),
            })

    logger.info("Matched pairs: %d. Unmatched eval: %d, Unmatched GT: %d", len(matched_pairs), len(unmatched_eval), len(unmatched_gt))

    # Write unmatched_cases.csv
    with open(unmatched_cases_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["reason", "test_case_id", "plant_name", "question"])
        writer.writeheader()
        for u in unmatched_eval:
            writer.writerow({"reason": u["reason"], "test_case_id": "", "plant_name": u.get("plant_name"), "question": u.get("question")})
        for u in unmatched_gt:
            writer.writerow({"reason": u["reason"], "test_case_id": u.get("test_case_id"), "plant_name": u.get("plant_name"), "question": u.get("question")})

    # 4. Run Evaluation
    evaluator = RunEvaluator(dict(gt_cases))
    case_results: list[CaseMetricResult] = []
    all_claim_annotations: list[ClaimAnnotation] = []

    # Accumulators for micro-averaging
    total_retrieved_facts = 0
    total_relevant_facts = 0
    total_verifiable_claims = 0
    total_supported_claims = 0
    total_traceable_claims = 0

    # Lists for macro-averaging
    valid_precision_scores: list[float] = []
    valid_groundedness_scores: list[float] = []
    valid_traceability_scores: list[float] = []
    completeness_scores: list[float] = []

    precision_na_count = 0
    groundedness_na_count = 0
    traceability_na_count = 0

    t0 = datetime.now(timezone.utc)
    for i, (eval_rec, gt_c) in enumerate(matched_pairs, 1):
        if i % 100 == 0 or i == 1 or i == len(matched_pairs):
            logger.info("Evaluating case %d / %d ...", i, len(matched_pairs))

        metric_res, annotations = evaluator.evaluate_case(eval_rec, gt_c)
        case_results.append(metric_res)
        all_claim_annotations.extend(annotations)

        # Precision stats
        total_retrieved_facts += metric_res.retrieved_fact_count
        total_relevant_facts += metric_res.relevant_retrieved_fact_count
        if isinstance(metric_res.graph_precision, (int, float)):
            valid_precision_scores.append(metric_res.graph_precision)
        else:
            precision_na_count += 1

        # Groundedness & Traceability stats
        total_verifiable_claims += metric_res.factual_claim_count
        total_supported_claims += metric_res.supported_claim_count
        total_traceable_claims += metric_res.traceable_claim_count

        if isinstance(metric_res.groundedness, (int, float)):
            valid_groundedness_scores.append(metric_res.groundedness)
        else:
            groundedness_na_count += 1

        if isinstance(metric_res.traceability, (int, float)):
            valid_traceability_scores.append(metric_res.traceability)
        else:
            traceability_na_count += 1

        completeness_scores.append(metric_res.trace_completeness)

    t1 = datetime.now(timezone.utc)
    elapsed_sec = (t1 - t0).total_seconds()
    logger.info("Evaluation finished in %.2f seconds.", elapsed_sec)

    # 5. Write case_metrics.csv
    logger.info("Writing %s ...", case_metrics_csv_path)
    case_fieldnames = [
        "test_case_id", "plant_name", "question_id", "question",
        "ground_truth_status", "expected_fact_count", "retrieved_fact_count",
        "relevant_retrieved_fact_count", "graph_precision", "factual_claim_count",
        "supported_claim_count", "groundedness", "traceable_claim_count",
        "traceability", "trace_completeness", "review_notes"
    ]
    with open(case_metrics_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=case_fieldnames)
        writer.writeheader()
        for res in case_results:
            writer.writerow(res.to_csv_dict())

    # 6. Write claim_annotations.csv
    logger.info("Writing %s ...", claim_annotations_csv_path)
    claim_fieldnames = [
        "claim_id", "test_case_id", "plant_name", "question_id",
        "answer_claim", "cited_evidence_ids", "supporting_retrieved_fact_ids",
        "support_status", "is_traceable", "reviewer_notes"
    ]
    with open(claim_annotations_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=claim_fieldnames)
        writer.writeheader()
        for ann in all_claim_annotations:
            writer.writerow(ann.to_csv_dict())

    # 7. Compute aggregate metrics
    micro_precision = total_relevant_facts / total_retrieved_facts if total_retrieved_facts > 0 else "N/A"
    macro_precision = sum(valid_precision_scores) / len(valid_precision_scores) if valid_precision_scores else "N/A"

    micro_groundedness = total_supported_claims / total_verifiable_claims if total_verifiable_claims > 0 else "N/A"
    macro_groundedness = sum(valid_groundedness_scores) / len(valid_groundedness_scores) if valid_groundedness_scores else "N/A"

    micro_traceability = total_traceable_claims / total_verifiable_claims if total_verifiable_claims > 0 else "N/A"
    macro_traceability = sum(valid_traceability_scores) / len(valid_traceability_scores) if valid_traceability_scores else "N/A"

    mean_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0.0

    aggregate_results: dict[str, Any] = {
        "timestamp": utc_iso_now(),
        "total_evaluated_cases": len(case_results),
        "total_claims_evaluated": len(all_claim_annotations),
        "graph_precision": {
            "definition": "relevant retrieved graph facts / all retrieved graph facts",
            "micro_averaged": round(micro_precision, 4) if isinstance(micro_precision, float) else micro_precision,
            "macro_averaged": round(macro_precision, 4) if isinstance(macro_precision, float) else macro_precision,
            "total_retrieved_facts": total_retrieved_facts,
            "total_relevant_retrieved_facts": total_relevant_facts,
            "valid_cases_count": len(valid_precision_scores),
            "na_cases_count": precision_na_count,
        },
        "groundedness": {
            "definition": "supported factual claims in final response / all verifiable factual claims in final response",
            "micro_averaged": round(micro_groundedness, 4) if isinstance(micro_groundedness, float) else micro_groundedness,
            "macro_averaged": round(macro_groundedness, 4) if isinstance(macro_groundedness, float) else macro_groundedness,
            "total_verifiable_claims": total_verifiable_claims,
            "total_supported_claims": total_supported_claims,
            "valid_cases_count": len(valid_groundedness_scores),
            "na_cases_count": groundedness_na_count,
        },
        "traceability": {
            "definition": "factual claims linked to concrete supporting retrieved evidence / all verifiable factual claims",
            "micro_averaged": round(micro_traceability, 4) if isinstance(micro_traceability, float) else micro_traceability,
            "macro_averaged": round(macro_traceability, 4) if isinstance(macro_traceability, float) else macro_traceability,
            "total_verifiable_claims": total_verifiable_claims,
            "total_traceable_claims": total_traceable_claims,
            "valid_cases_count": len(valid_traceability_scores),
            "na_cases_count": traceability_na_count,
        },
        "trace_completeness": {
            "definition": "ratio of expected pipeline events, successful tool calls, and complete trace representations",
            "mean_completeness": round(mean_completeness, 4),
            "evaluated_cases": len(completeness_scores),
        },
    }

    with open(aggregate_metrics_json_path, "w", encoding="utf-8") as f:
        json.dump(aggregate_results, f, indent=2)
    logger.info("Saved aggregate metrics to %s", aggregate_metrics_json_path)

    # 8. Write evaluation_report.json
    report: dict[str, Any] = {
        "timestamp": utc_iso_now(),
        "elapsed_seconds": round(elapsed_sec, 2),
        "ground_truth_cases_total": len(gt_cases),
        "evaluation_records_total": len(eval_records),
        "matched_cases_total": len(matched_pairs),
        "unmatched_evaluation_records": len(unmatched_eval),
        "unmatched_ground_truth_cases": len(unmatched_gt),
        "aggregate_summary": {
            "graph_precision_micro": aggregate_results["graph_precision"]["micro_averaged"],
            "graph_precision_macro": aggregate_results["graph_precision"]["macro_averaged"],
            "groundedness_micro": aggregate_results["groundedness"]["micro_averaged"],
            "groundedness_macro": aggregate_results["groundedness"]["macro_averaged"],
            "traceability_micro": aggregate_results["traceability"]["micro_averaged"],
            "traceability_macro": aggregate_results["traceability"]["macro_averaged"],
            "trace_completeness_mean": aggregate_results["trace_completeness"]["mean_completeness"],
        },
        "notes": (
            "Evaluation performed strictly on existing execution runs without regenerating answers. "
            "Graph Precision evaluates actual retrieved graph facts in traces against verified Neo4j ground truth. "
            "Groundedness evaluates response claims against execution-retrieved evidence. "
            "Traceability verifies both concrete citation pointers and that the cited record supports the claim. "
            "Where denominator was 0, N/A was reported."
        ),
    }

    with open(evaluation_report_json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Saved evaluation report to %s", evaluation_report_json_path)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate existing IMPARK evaluation runs against verified ground truth.")
    parser.add_argument(
        "--ground-truth",
        "-g",
        type=Path,
        default=Path("data/ground_truth/ground_truth_cases.jsonl"),
        help="Path to ground_truth_cases.jsonl",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path("data/all_plants_evaluation.jsonl"),
        help="Path to evaluation JSONL file containing existing runs (e.g., data/all_plants_evaluation.jsonl)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("data/metric_results"),
        help="Directory to save metric results and annotations",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files if present",
    )

    args = parser.parse_args()

    # Fallback to combine parts if input file does not exist
    if not args.input.exists():
        part1 = Path("data/evaluation_part1.jsonl")
        part2 = Path("data/evaluation_part2.jsonl")
        if part1.exists() and part2.exists():
            logger.info("Consolidated file %s not found. Combining %s and %s ...", args.input, part1, part2)
            from scripts.combine_evaluation_parts import combine_parts
            combine_parts(part1, part2, args.input)

    evaluate_runs(
        ground_truth_path=args.ground_truth,
        evaluation_jsonl_path=args.input,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
