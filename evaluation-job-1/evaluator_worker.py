#!/usr/bin/env python3
"""Evaluator Worker for IMPARK Knowledge Graph & Agentic Runs (Job 2).

This script performs batch inference evaluation over existing IMPARK execution traces:
1. Connects to Docker Bucket Storage using authentication credentials (username/password)
   and fetches verified ground-truth .txt context files.
2. Reads execution traces from JSONL (data/all_plants_evaluation.jsonl).
3. Slices the ground truth for each question using the exact 'identifiers' present in the evaluation record.
4. Mathematically calculates:
   - Tool Call Accuracy (ratio of successful tool calls, verifying expected graph retrieval invocation)
   - Graph Retrieval Time (duration_ms extracted directly from retrieve_plant_graph calls)
5. Uses semantic analysis with SentenceTransformer ('all-MiniLM-L6-v2') to compute:
   - Groundedness Score (semantic alignment of response claims against sliced ground truth facts)
   - Hallucination Rate (ratio of unsupported / contradictory claims)
6. Writes per-case metrics into PostgreSQL table `case_evaluation_metrics` and aggregates into `aggregate_evaluation_metrics`.
7. Exports CSV and JSON reports for external validation and Grafana visualization.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import torch
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("impark.evaluator_worker")


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


def clean_alphanumeric(text: str) -> str:
    """Normalize string to lowercase alphanumeric characters with single spaces."""
    return re.sub(r"[^a-zA-Z0-9]", " ", text).lower()


# ============================================================================
# Ground Truth Context Parser & Slicer
# ============================================================================

class GroundTruthContextSlicer:
    """Parses and slices plant context .txt files by question identifiers."""

    def __init__(self, raw_txt: str, plant_name: str) -> None:
        self.raw_txt = raw_txt
        self.plant_name = plant_name
        self.sections = self._parse_sections(raw_txt)

    def _parse_sections(self, text: str) -> dict[str, list[dict[str, str]]]:
        """Parse structured sections and pipe-separated key-value lines."""
        sections: dict[str, list[dict[str, str]]] = {
            "summary": [],
            "plant_details": [],
            "plant_parts": [],
            "therapeutic_uses": [],
            "bioactivities": [],
            "protein_targets": [],
            "phytochemicals": [],
            "documents": [],
        }

        current_section = "summary"
        for line in text.split("\n"):
            line_str = line.strip()
            if not line_str or line_str.startswith("---") or line_str.startswith("==="):
                continue

            lower_line = line_str.lower()
            if "plant details" in lower_line:
                current_section = "plant_details"
                continue
            elif "plant parts" in lower_line:
                current_section = "plant_parts"
                continue
            elif "therapeutic uses" in lower_line:
                current_section = "therapeutic_uses"
                continue
            elif "bioactivities" in lower_line:
                current_section = "bioactivities"
                continue
            elif "protein targets" in lower_line:
                current_section = "protein_targets"
                continue
            elif "phytochemicals" in lower_line:
                current_section = "phytochemicals"
                continue
            elif "documents" in lower_line:
                current_section = "documents"
                continue

            if "|" in line_str:
                clean_line = re.sub(r"^\d+\.\s*", "", line_str)
                parts = clean_line.split("|")
                item: dict[str, str] = {}
                for part in parts:
                    if ":" in part:
                        k, v = part.split(":", 1)
                        item[k.strip().lower()] = v.strip()
                if item:
                    sections[current_section].append(item)
            elif ":" in line_str and current_section in ("summary", "plant_details"):
                k, v = line_str.split(":", 1)
                sections[current_section].append({k.strip().lower(): v.strip()})

        return sections

    def slice_for_identifiers(
        self,
        identifiers: list[str],
        question: str,
        tool_calling: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Extract sliced factual statements relevant to the given identifiers."""
        facts: list[str] = []
        id_set = {i.lower() for i in identifiers}
        q_lower = question.lower()
        is_leaf_scoped = "leaf" in q_lower or "leaves" in q_lower

        # 1. Phytochemicals
        if any(k in id_set for k in ["phytochemical_name", "smiles", "inchi_key", "classyfire_class", "classyfire_kingdom", "classyfire_superclass", "classyfire_subclass"]):
            for item in self.sections["phytochemicals"]:
                name = item.get("phytochemical_name", "")
                if not name:
                    continue
                parts = [f"Phytochemical {name}"]
                if "smiles" in id_set and "smiles" in item:
                    parts.append(f"SMILES {item['smiles']}")
                if "inchi_key" in id_set and "inchi_key" in item:
                    parts.append(f"InChIKey {item['inchi_key']}")
                if "chembl_id" in id_set and "chembl_id" in item:
                    parts.append(f"ChEMBL ID {item['chembl_id']}")
                if "imppat_id" in id_set and "imppat_id" in item:
                    parts.append(f"IMPPAT ID {item['imppat_id']}")
                if any(k in id_set for k in ["classyfire_class", "classyfire_kingdom", "classyfire_superclass", "classyfire_subclass"]):
                    cls_parts = [
                        item.get("classyfire_kingdom", ""),
                        item.get("classyfire_superclass", ""),
                        item.get("classyfire_class", ""),
                        item.get("classyfire_subclass", ""),
                    ]
                    cls_desc = " > ".join([p for p in cls_parts if p and p != "NA"])
                    if cls_desc:
                        parts.append(f"classified as {cls_desc}")
                facts.append(". ".join(parts))

        # 2. Therapeutic Uses
        if "therapeutic_use" in id_set:
            for item in self.sections["therapeutic_uses"]:
                use = item.get("therapeutic_use", "")
                if not use:
                    continue
                if is_leaf_scoped:
                    part_str = item.get("plant_part", "")
                    if part_str and "leaf" not in part_str.lower():
                        continue
                parts = [f"Therapeutic use: {use}"]
                if any(k in id_set for k in ["mesh_category", "mesh_category_name", "mesh_sub_category_name"]):
                    parts.append(f"category: {item.get('mesh_category_name', '')} ({item.get('mesh_sub_category_name', '')})")
                facts.append(", ".join(parts))

        # 3. Plant Parts
        if "plant_part" in id_set:
            for item in self.sections["plant_parts"]:
                part_name = item.get("plant_part", "")
                if part_name:
                    facts.append(f"Recorded plant part: {part_name} for {self.plant_name}")

        # 4. Bioactivities
        if any(k in id_set for k in ["bioactivity_id", "standard_type", "standard_value", "standard_relation", "standard_units", "high_confidence_tier"]):
            for item in self.sections["bioactivities"]:
                stype = item.get("standard_type", "")
                sval = item.get("standard_value", "")
                srel = item.get("standard_relation", "=")
                sunit = item.get("standard_units", "")
                tier = item.get("high_confidence_tier", "")
                bid = item.get("bioactivity_id", "")
                desc = f"Bioactivity measurement {bid}: {stype} {srel} {sval} {sunit} (Tier: {tier})"
                facts.append(desc)

        # 5. Protein Targets
        if "target_name" in id_set:
            for item in self.sections["protein_targets"]:
                tname = item.get("target_name", "")
                if not tname:
                    continue
                parts = [f"Protein target: {tname}"]
                if "target_organism" in id_set and "target_organism" in item:
                    parts.append(f"organism: {item['target_organism']}")
                if "target_type" in id_set and "target_type" in item:
                    parts.append(f"type: {item['target_type']}")
                if "uniprot_id" in id_set and "uniprot_id" in item:
                    parts.append(f"UniProt ID: {item['uniprot_id']}")
                if "target_chembl_id" in id_set and "target_chembl_id" in item:
                    parts.append(f"ChEMBL Target: {item['target_chembl_id']}")
                facts.append(", ".join(parts))

        # 6. Plant Details / Common Names / Aliases
        if any(k in id_set for k in ["alias", "normalized_alias", "alias_type", "language"]):
            for item in self.sections["plant_details"]:
                if "common_names" in item:
                    facts.append(f"Common names: {item['common_names']}")
            if tool_calling:
                for call in tool_calling:
                    if call.get("tool_name") == "retrieve_plant_graph":
                        res = call.get("result", {})
                        for f in res.get("facts", []):
                            rec = f.get("record", {})
                            if "alias" in rec:
                                facts.append(f"Alias {rec.get('alias')}: type {rec.get('alias_type')} language {rec.get('language')}")

        # Fallback if no specific entries were parsed
        if not facts:
            for sec in ["therapeutic_uses", "plant_parts", "phytochemicals", "bioactivities"]:
                for item in self.sections[sec][:10]:
                    vals = [f"{k}: {v}" for k, v in item.items() if k in id_set]
                    if vals:
                        facts.append(f"{self.plant_name} - " + ", ".join(vals))

        return facts


# ============================================================================
# Answer-Item Extractor (Semantic Fact Isolation)
# ============================================================================

def extract_answer_items(response_text: str, question: str, identifiers: list[str]) -> list[str]:
    """Extract concrete answer elements from the model response based on question and identifiers.

    Isolates specific factual answer entities, classifications, accession IDs,
    bioactivity metrics, and plant parts, filtering out generic commentary,
    chemical explanations, and disclaimers.
    """
    if not response_text:
        return []

    answers: list[str] = []
    id_set = {i.lower() for i in identifiers}
    q_lower = question.lower()

    # 1. Bullet points with bold headers: * **Name**: Description or * **Name**
    bullet_bolds = re.findall(r"^[\*\-\d\.]+\s+\*\*([^\*:]+)\*\*[:\s]*(.*)$", response_text, re.MULTILINE)
    for name, desc in bullet_bolds:
        name_clean = name.strip()
        desc_clean = re.sub(r"\[\d+\]", "", desc).strip()
        if any(k in id_set for k in ["classyfire_class", "classyfire_kingdom", "classyfire_superclass", "classyfire_subclass", "smiles", "inchi_key", "uniprot_id", "target_chembl_id", "mesh_category"]):
            answers.append(f"{name_clean}: {desc_clean}")
        else:
            answers.append(name_clean)

    # 2. Sub-bullets with specific properties (SMILES, InChIKey, UniProt, ChEMBL)
    sub_props = re.findall(r"[\*\-\s]+(SMILES|InChIKey|UniProt ID|ChEMBL ID|ChEMBL Target ID|Potency|Kd|IC50|EC50|Ki):\s*([^\s\[\]]+)", response_text, re.IGNORECASE)
    for k, v in sub_props:
        answers.append(f"{k}: {v}")

    # 3. Plain bullet lines
    plain_bullets = re.findall(r"^[\*\-\d\.]+\s+([^\*\n]+?)(?:\s*\[\d+\])?$", response_text, re.MULTILINE)
    for p in plain_bullets:
        p_clean = p.strip()
        if len(p_clean) > 2 and not any(p_clean.lower().startswith(x) for x in ["the ", "here ", "this ", "each ", "more ", "for example"]):
            p_sub = re.sub(r"[\*_]", "", p_clean)
            answers.append(p_sub)

    # 4. Plant parts extraction for plant part queries
    if "plant_part" in id_set or "parts of this plant" in q_lower:
        known_parts = ["flower", "leaf", "leaves", "rhizome", "root", "roots", "seed", "seeds", "stem", "tuber", "whole plant", "bark", "fruit", "aerial parts"]
        for part in known_parts:
            if re.search(r"\b" + part + r"\b", response_text, re.IGNORECASE):
                norm = part.rstrip("s") if part not in ("whole plant", "aerial parts") else part
                answers.append(norm)

    # 5. Bioactivity measurements extraction
    if any(k in id_set for k in ["standard_type", "standard_value", "standard_relation", "standard_units"]):
        num_units = re.findall(r"(\d+(?:\.\d+)?)\s*(nM|uM|µM|mM|pM|%)", response_text, re.IGNORECASE)
        for val, unit in num_units:
            answers.append(f"{val} {unit}")
        rel_signs = re.findall(r"(?:relation sign of\s*['\"]?([=><])['\"]?|([=><])\s*\d+)", response_text)
        for r1, r2 in rel_signs:
            sign = r1 or r2
            if sign:
                answers.append(f"relation: {sign}")
        for stype in ["IC50", "Kd", "Ki", "Potency", "EC50"]:
            if re.search(r"\b" + stype + r"\b", response_text):
                answers.append(f"measurement_type: {stype}")

    # 6. Specific identifiers (ChEMBL, IMPPAT, UniProt, Bioactivity)
    ids_found = re.findall(r"(CHEMBL\d+|IMPHY\d+|P\d{5}|Q\d{5}|BA_\d+)", response_text)
    for ident in ids_found:
        answers.append(ident)

    # 7. Fallback: bold terms if answers still empty
    if not answers:
        bolds = re.findall(r"\*\*([^\*]+)\*\*", response_text)
        for b in bolds:
            b_clean = b.strip()
            if len(b_clean) > 2 and not any(p in b_clean.lower() for p in ["note", "disclaimer", "warning", "summary"]):
                answers.append(b_clean)

    return list(dict.fromkeys(answers))


def extract_response_claims(response_text: str) -> list[str]:
    """Compatibility wrapper around answer extraction."""
    return extract_answer_items(response_text, "", [])


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class EvaluatedCase:
    id: int
    test_case_id: str
    plant_name: str
    question: str
    identifiers: list[str]
    tool_call_accuracy: float
    graph_retrieval_time_ms: float
    groundedness_score: float
    hallucination_rate: float
    total_claims: int
    grounded_claims: int
    hallucinated_claims: int
    total_tool_calls: int
    successful_tool_calls: int
    response_text: str
    evaluated_at: str = field(default_factory=utc_iso_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "test_case_id": self.test_case_id,
            "plant_name": self.plant_name,
            "question": self.question,
            "identifiers": json.dumps(self.identifiers),
            "tool_call_accuracy": round(self.tool_call_accuracy, 4),
            "graph_retrieval_time_ms": round(self.graph_retrieval_time_ms, 2),
            "groundedness_score": round(self.groundedness_score, 4),
            "hallucination_rate": round(self.hallucination_rate, 4),
            "total_claims": self.total_claims,
            "grounded_claims": self.grounded_claims,
            "hallucinated_claims": self.hallucinated_claims,
            "total_tool_calls": self.total_tool_calls,
            "successful_tool_calls": self.successful_tool_calls,
            "response_text": self.response_text,
            "evaluated_at": self.evaluated_at,
        }


# ============================================================================
# Evaluator Engine
# ============================================================================

class EvaluatorWorker:
    """Rigid, production-grade Evaluator Worker (Job 2)."""

    def __init__(
        self,
        minio_endpoint: str = "127.0.0.1:9000",
        minio_access_key: str = "minioadmin",
        minio_secret_key: str = "minioadmin123",
        minio_bucket: str = "impark-ground-truth",
        minio_secure: bool = False,
        embedding_model_name: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.58,
    ) -> None:
        self.minio_endpoint = minio_endpoint
        self.minio_access_key = minio_access_key
        self.minio_secret_key = minio_secret_key
        self.minio_bucket = minio_bucket
        self.minio_secure = minio_secure
        self.similarity_threshold = similarity_threshold

        logger.info("Initializing SentenceTransformer model '%s'...", embedding_model_name)
        try:
            self.model = SentenceTransformer(embedding_model_name, local_files_only=True)
        except Exception:
            self.model = SentenceTransformer(embedding_model_name)
        logger.info("SentenceTransformer model loaded.")

        self.gt_cache: dict[str, GroundTruthContextSlicer] = {}
        self.fact_emb_cache: dict[tuple[str, ...], Any] = {}

    def fetch_ground_truth_from_bucket(self) -> dict[str, GroundTruthContextSlicer]:
        """Login to Docker Bucket Storage and download all plant ground-truth .txt context files."""
        proto = "https" if self.minio_secure else "http"
        base_url = f"{proto}://{self.minio_endpoint}"
        auth_bytes = f"{self.minio_access_key}:{self.minio_secret_key}".encode("utf-8")
        auth_header = f"Basic {base64.b64encode(auth_bytes).decode('ascii')}"

        logger.info("Logging into Bucket Storage at %s as '%s'...", base_url, self.minio_access_key)
        list_url = f"{base_url}/{self.minio_bucket}"
        req = urllib.request.Request(list_url, method="GET")
        req.add_header("Authorization", auth_header)
        req.add_header("Accept", "application/json")

        req.add_header("Connection", "close")
        objects = []
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    objects = data.get("objects", [])
                break
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise PermissionError("Bucket Authentication Failed! Invalid username or password.") from e
                if attempt == 2:
                    raise
                time.sleep(1)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1)

        logger.info("Found %d ground-truth .txt objects in bucket '%s'.", len(objects), self.minio_bucket)

        for idx, obj in enumerate(objects):
            obj_name = obj["name"]
            if not obj_name.endswith(".txt"):
                continue

            quoted_name = urllib.parse.quote(obj_name)
            get_url = f"{base_url}/{self.minio_bucket}/{quoted_name}"
            get_req = urllib.request.Request(get_url, method="GET")
            get_req.add_header("Authorization", auth_header)
            get_req.add_header("Connection", "close")

            content = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(get_req, timeout=15) as obj_resp:
                        content = obj_resp.read().decode("utf-8")
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(1)

            p_name = obj_name.replace("_context.txt", "").replace(".txt", "").strip()
            self.gt_cache[p_name.lower()] = GroundTruthContextSlicer(raw_txt=content, plant_name=p_name)
            if (idx + 1) % 10 == 0 or idx == len(objects) - 1:
                logger.info("Downloaded ground truth from bucket: %d/%d (%s)", idx + 1, len(objects), p_name)

        logger.info("Successfully loaded and cached %d plant contexts from bucket.", len(self.gt_cache))
        return self.gt_cache

    def evaluate_case(self, case_index: int, record: dict[str, Any]) -> EvaluatedCase:
        """Evaluate a single test case trace against sliced ground truth from bucket."""
        plant_name = record.get("plant_name", "").strip()
        question = record.get("question", "").strip()
        identifiers = record.get("identifier", [])
        response_text = record.get("response", "") or ""
        traces = record.get("traces", {})
        tool_calling = traces.get("tool_calling", [])

        test_case_id = f"TC_{case_index+1:03d}_{plant_name.replace(' ', '_')}"

        # 1. Mathematical calculation: Tool Call Accuracy
        total_tool_calls = len(tool_calling)
        successful_tool_calls = 0
        has_graph_call = False
        graph_retrieval_time_ms = 0.0

        for call in tool_calling:
            tname = call.get("tool_name")
            status = call.get("status")
            dur = call.get("duration_ms") or 0.0

            if status in ("ok", None):
                successful_tool_calls += 1

            if tname == "retrieve_plant_graph":
                has_graph_call = True
                graph_retrieval_time_ms += float(dur)

        if total_tool_calls > 0:
            tool_call_accuracy = successful_tool_calls / total_tool_calls
            if not has_graph_call:
                tool_call_accuracy *= 0.5
        else:
            tool_call_accuracy = 0.0

        # 2. Slice ground truth from bucket cache
        slicer = self.gt_cache.get(plant_name.lower())
        if slicer:
            sliced_facts = slicer.slice_for_identifiers(identifiers, question, tool_calling)
        else:
            sliced_facts = []

        # 3. Extract concrete answer items
        ans_items = extract_answer_items(response_text, question, identifiers)
        total_claims = len(ans_items)

        # 4. Semantic analysis via SentenceTransformer & verification against ground truth
        if total_claims == 0:
            if not sliced_facts or any(term in response_text.lower() for term in ["no records", "not found", "not documented", "no direct"]):
                groundedness_score = 1.0
                hallucination_rate = 0.0
                grounded_claims = 0
                hallucinated_claims = 0
            else:
                groundedness_score = 0.0
                hallucination_rate = 1.0
                grounded_claims = 0
                hallucinated_claims = 0
        elif not sliced_facts:
            if any(term in response_text.lower() for term in ["no records", "not found", "not documented", "no direct"]):
                groundedness_score = 1.0
                hallucination_rate = 0.0
                grounded_claims = total_claims
                hallucinated_claims = 0
            else:
                groundedness_score = 0.0
                hallucination_rate = 1.0
                grounded_claims = 0
                hallucinated_claims = total_claims
        else:
            ans_emb = self.model.encode(ans_items, convert_to_tensor=True)
            facts_key = tuple(sliced_facts)
            if facts_key in self.fact_emb_cache:
                fact_emb = self.fact_emb_cache[facts_key]
            else:
                fact_emb = self.model.encode(sliced_facts, convert_to_tensor=True)
                self.fact_emb_cache[facts_key] = fact_emb

            sim_matrix = cos_sim(ans_emb, fact_emb)
            max_sims = torch.max(sim_matrix, dim=1).values.tolist()

            gt_full_clean = " " + " ".join([clean_alphanumeric(g) for g in sliced_facts]) + " "
            raw_gt_lower = slicer.raw_txt.lower() if slicer else ""

            grounded_claims = 0
            for item_idx, sim in enumerate(max_sims):
                item_raw = ans_items[item_idx]
                val = item_raw.split(":", 1)[1].strip() if ":" in item_raw else item_raw
                val_clean = clean_alphanumeric(val).strip()

                is_in_gt = (
                    (len(val_clean) >= 3 and f" {val_clean} " in gt_full_clean)
                    or any(val.lower() in g.lower() for g in sliced_facts)
                    or (len(val.strip()) >= 3 and val.lower() in raw_gt_lower)
                )

                if sim >= self.similarity_threshold or is_in_gt:
                    grounded_claims += 1

            groundedness_score = grounded_claims / total_claims
            hallucination_rate = 1.0 - groundedness_score
            hallucinated_claims = total_claims - grounded_claims

        return EvaluatedCase(
            id=case_index + 1,
            test_case_id=test_case_id,
            plant_name=plant_name,
            question=question,
            identifiers=identifiers,
            tool_call_accuracy=tool_call_accuracy,
            graph_retrieval_time_ms=graph_retrieval_time_ms,
            groundedness_score=groundedness_score,
            hallucination_rate=hallucination_rate,
            total_claims=total_claims,
            grounded_claims=grounded_claims,
            hallucinated_claims=hallucinated_claims,
            total_tool_calls=total_tool_calls,
            successful_tool_calls=successful_tool_calls,
            response_text=response_text,
        )


# ============================================================================
# PostgreSQL Storage Pipeline
# ============================================================================

def store_metrics_in_postgres(
    cases: list[EvaluatedCase],
    pg_host: str = "127.0.0.1",
    pg_port: int = 5433,
    pg_user: str = "eval_admin",
    pg_pass: str = "eval_secret_pass",
    pg_db: str = "impark_evaluation",
) -> None:
    """Persist case and aggregate metric scores into PostgreSQL."""
    conn_str = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}?connect_timeout=15"
    logger.info("Connecting to PostgreSQL at %s:%d/%s ...", pg_host, pg_port, pg_db)

    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            # 1. Create table `case_evaluation_metrics`
            cur.execute("""
                CREATE TABLE IF NOT EXISTS case_evaluation_metrics (
                    id INT PRIMARY KEY,
                    test_case_id VARCHAR(100) NOT NULL,
                    plant_name VARCHAR(255) NOT NULL,
                    question TEXT NOT NULL,
                    identifiers TEXT NOT NULL,
                    tool_call_accuracy DOUBLE PRECISION NOT NULL,
                    graph_retrieval_time_ms DOUBLE PRECISION NOT NULL,
                    groundedness_score DOUBLE PRECISION NOT NULL,
                    hallucination_rate DOUBLE PRECISION NOT NULL,
                    total_claims INT NOT NULL,
                    grounded_claims INT NOT NULL,
                    hallucinated_claims INT NOT NULL,
                    total_tool_calls INT NOT NULL,
                    successful_tool_calls INT NOT NULL,
                    response_text TEXT,
                    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            # 2. Create table `aggregate_evaluation_metrics`
            cur.execute("""
                CREATE TABLE IF NOT EXISTS aggregate_evaluation_metrics (
                    id SERIAL PRIMARY KEY,
                    run_id VARCHAR(100) NOT NULL,
                    total_cases INT NOT NULL,
                    avg_groundedness DOUBLE PRECISION NOT NULL,
                    avg_hallucination_rate DOUBLE PRECISION NOT NULL,
                    avg_tool_call_accuracy DOUBLE PRECISION NOT NULL,
                    avg_graph_retrieval_time_ms DOUBLE PRECISION NOT NULL,
                    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)

            # Clean previous run
            cur.execute("DELETE FROM case_evaluation_metrics;")

            # 3. Batch insert case metrics
            insert_query = """
                INSERT INTO case_evaluation_metrics (
                    id, test_case_id, plant_name, question, identifiers,
                    tool_call_accuracy, graph_retrieval_time_ms, groundedness_score,
                    hallucination_rate, total_claims, grounded_claims,
                    hallucinated_claims, total_tool_calls, successful_tool_calls,
                    response_text, evaluated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                );
            """

            rows = [
                (
                    c.id, c.test_case_id, c.plant_name, c.question, json.dumps(c.identifiers),
                    c.tool_call_accuracy, c.graph_retrieval_time_ms, c.groundedness_score,
                    c.hallucination_rate, c.total_claims, c.grounded_claims,
                    c.hallucinated_claims, c.total_tool_calls, c.successful_tool_calls,
                    c.response_text, c.evaluated_at
                )
                for c in cases
            ]

            cur.executemany(insert_query, rows)

            # 4. Insert aggregate metrics
            avg_groundedness = sum(c.groundedness_score for c in cases) / len(cases)
            avg_hallucination = sum(c.hallucination_rate for c in cases) / len(cases)
            avg_tool_acc = sum(c.tool_call_accuracy for c in cases) / len(cases)
            avg_graph_ms = sum(c.graph_retrieval_time_ms for c in cases) / len(cases)

            cur.execute("""
                INSERT INTO aggregate_evaluation_metrics (
                    run_id, total_cases, avg_groundedness, avg_hallucination_rate,
                    avg_tool_call_accuracy, avg_graph_retrieval_time_ms
                ) VALUES (%s, %s, %s, %s, %s, %s);
            """, (
                f"eval_run_{int(time.time())}",
                len(cases),
                round(avg_groundedness, 4),
                round(avg_hallucination, 4),
                round(avg_tool_acc, 4),
                round(avg_graph_ms, 2)
            ))

            conn.commit()
            logger.info("Successfully persisted %d case metrics and aggregate summary into PostgreSQL.", len(cases))


# ============================================================================
# Main Workflow
# ============================================================================

def run_evaluation(
    jsonl_path: Path,
    output_dir: Path,
    minio_endpoint: str = "127.0.0.1:9000",
    minio_access_key: str = "minioadmin",
    minio_secret_key: str = "minioadmin123",
    minio_bucket: str = "impark-ground-truth",
    pg_host: str = "127.0.0.1",
    pg_port: int = 5433,
    pg_user: str = "eval_admin",
    pg_pass: str = "eval_secret_pass",
    pg_db: str = "impark_evaluation",
) -> dict[str, Any]:
    """Execute complete Job 2 evaluation pipeline."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_out_path = output_dir / "case_evaluation_metrics.csv"
    summary_out_path = output_dir / "aggregate_metrics.json"

    # 1. Initialize Evaluator & download ground truth from MinIO
    evaluator = EvaluatorWorker(
        minio_endpoint=minio_endpoint,
        minio_access_key=minio_access_key,
        minio_secret_key=minio_secret_key,
        minio_bucket=minio_bucket,
        minio_secure=False,
    )
    evaluator.fetch_ground_truth_from_bucket()

    # 2. Load execution traces
    logger.info("Loading execution traces from %s ...", jsonl_path)
    records: list[dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                records.append(json.loads(line_str))
    logger.info("Loaded %d execution records.", len(records))

    # 3. Evaluate each case
    t0 = time.time()
    evaluated_cases: list[EvaluatedCase] = []
    for idx, rec in enumerate(records):
        if (idx + 1) % 50 == 0 or idx == 0 or idx == len(records) - 1:
            logger.info("Evaluating trace %d / %d ...", idx + 1, len(records))
        ec = evaluator.evaluate_case(idx, rec)
        evaluated_cases.append(ec)

    elapsed_sec = time.time() - t0
    logger.info("Completed evaluation over %d cases in %.2f seconds.", len(evaluated_cases), elapsed_sec)

    # 4. Compute aggregate metrics
    avg_groundedness = sum(c.groundedness_score for c in evaluated_cases) / len(evaluated_cases)
    avg_hallucination = sum(c.hallucination_rate for c in evaluated_cases) / len(evaluated_cases)
    avg_tool_acc = sum(c.tool_call_accuracy for c in evaluated_cases) / len(evaluated_cases)
    avg_graph_ms = sum(c.graph_retrieval_time_ms for c in evaluated_cases) / len(evaluated_cases)

    aggregate_summary = {
        "timestamp": utc_iso_now(),
        "total_cases_evaluated": len(evaluated_cases),
        "elapsed_seconds": round(elapsed_sec, 2),
        "mean_groundedness_score": round(avg_groundedness, 4),
        "mean_hallucination_rate": round(avg_hallucination, 4),
        "mean_tool_call_accuracy": round(avg_tool_acc, 4),
        "mean_graph_retrieval_time_ms": round(avg_graph_ms, 2),
        "bucket_source": f"s3://{minio_bucket}",
    }

    # 5. Save CSV file immediately
    logger.info("Writing CSV output to %s ...", csv_out_path)
    fieldnames = list(evaluated_cases[0].to_dict().keys())
    with open(csv_out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in evaluated_cases:
            writer.writerow(c.to_dict())

    # 6. Save JSON summary
    with open(summary_out_path, "w", encoding="utf-8") as f:
        json.dump(aggregate_summary, f, indent=2)

    # 7. Persist to PostgreSQL
    try:
        store_metrics_in_postgres(
            cases=evaluated_cases,
            pg_host=pg_host,
            pg_port=pg_port,
            pg_user=pg_user,
            pg_pass=pg_pass,
            pg_db=pg_db,
        )
    except Exception as exc:
        logger.error("Error storing metrics in PostgreSQL: %s", exc)

    print("\n" + "=" * 70)
    print("JOB 2: IMPARK EVALUATION WORKER COMPLETE SUMMARY")
    print("=" * 70)
    print(f"  Total Cases Evaluated:           {len(evaluated_cases)}")
    print(f"  Mean Groundedness Score:         {avg_groundedness:.2%}")
    print(f"  Mean Hallucination Rate:         {avg_hallucination:.2%}")
    print(f"  Mean Tool Call Accuracy:         {avg_tool_acc:.2%}")
    print(f"  Avg Graph Retrieval Time:        {avg_graph_ms:.2f} ms")
    print(f"  Total Evaluation Time:           {elapsed_sec:.1f} s")
    print("=" * 70)
    print(f"Results written to: {csv_out_path}")
    print(f"Summary written to: {summary_out_path}")
    print(f"PostgreSQL Table:   case_evaluation_metrics on port {pg_port}")
    print("=" * 70 + "\n")

    return aggregate_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluator Worker (Job 2) for IMPARK execution traces.")
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "all_plants_evaluation.jsonl",
        help="Path to evaluation JSONL file containing complete agent traces",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="Directory to save evaluation reports and CSV",
    )
    parser.add_argument(
        "--minio-endpoint",
        default=os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
        help="Bucket endpoint (default: 127.0.0.1:9000)",
    )
    parser.add_argument(
        "--minio-access-key",
        default=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        help="Bucket access key / user (default: minioadmin)",
    )
    parser.add_argument(
        "--minio-secret-key",
        default=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        help="Bucket secret key / password (default: minioadmin123)",
    )
    parser.add_argument(
        "--minio-bucket",
        default=os.getenv("MINIO_BUCKET", "impark-ground-truth"),
        help="Bucket containing ground-truth context files",
    )
    parser.add_argument(
        "--pg-host",
        default=os.getenv("PG_HOST", "127.0.0.1"),
        help="PostgreSQL host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--pg-port",
        type=int,
        default=int(os.getenv("PG_PORT", "5433")),
        help="PostgreSQL port (default: 5433)",
    )
    parser.add_argument(
        "--pg-user",
        default=os.getenv("PG_USER", "eval_admin"),
        help="PostgreSQL user (default: eval_admin)",
    )
    parser.add_argument(
        "--pg-pass",
        default=os.getenv("PG_PASSWORD", "eval_secret_pass"),
        help="PostgreSQL password",
    )
    parser.add_argument(
        "--pg-db",
        default=os.getenv("PG_DATABASE", "impark_evaluation"),
        help="PostgreSQL database name (default: impark_evaluation)",
    )

    args = parser.parse_args()

    run_evaluation(
        jsonl_path=args.input,
        output_dir=args.output_dir,
        minio_endpoint=args.minio_endpoint,
        minio_access_key=args.minio_access_key,
        minio_secret_key=args.minio_secret_key,
        minio_bucket=args.minio_bucket,
        pg_host=args.pg_host,
        pg_port=args.pg_port,
        pg_user=args.pg_user,
        pg_pass=args.pg_pass,
        pg_db=args.pg_db,
    )


if __name__ == "__main__":
    main()
