"""Ground-Truth Generation Pipeline for IMPARK Medicinal Plant Evaluation.

Extracts verified facts independently from the Neo4j knowledge graph for all
evaluation plant-question pairs, without using model outputs or agent traces.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.agents.common.parts import PART_NAMES
from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import Neo4jConfig, load_neo4j_config
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.neo4j.errors import GraphDatabaseError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("impark.ground_truth")


def utc_iso_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def normalize_text(text: str | None) -> str:
    """Safe textual normalization for comparison."""
    if text is None:
        return ""
    # Normalize unicode quotes and dashes
    s = text.strip()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\s+", " ", s)
    return s


def slugify(text: str) -> str:
    """Create a clean alphanumeric slug."""
    s = normalize_text(text).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def load_xlsx_records(file_path: Path) -> list[dict[str, Any]]:
    """Parse Excel (.xlsx) file using standard library zipfile and XML parser."""
    if not file_path.exists():
        raise FileNotFoundError(f"Questions file not found: {file_path}")

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


def parse_identifier_list(raw_identifier: Any) -> list[str]:
    """Parse identifier field which may be a JSON string, a Python list, or a comma-separated string."""
    if isinstance(raw_identifier, list):
        return [str(x).strip() for x in raw_identifier if str(x).strip()]
    if isinstance(raw_identifier, str):
        val = raw_identifier.strip()
        if val.startswith("[") and val.endswith("]"):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                pass
            # Fallback if json parse fails: strip brackets and quotes
            inner = val[1:-1]
            parts = [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
            return parts
        elif "," in val:
            return [p.strip().strip("'\"") for p in val.split(",") if p.strip()]
        elif val:
            return [val.strip("'\"")]
    return []


@dataclass
class ExpectedFact:
    fact_id: str
    test_case_id: str
    plant_name: str
    question_id: str
    question: str
    attribute_identifier: str
    expected_fact: str
    record: dict[str, Any] = field(default_factory=dict)
    subject_node_label: str = ""
    subject_node_id: str = ""
    relationship_path: str = ""
    target_node_label: str = ""
    target_node_id: str = ""
    source: str | None = None
    source_url: str | None = None
    verified: bool = True
    review_notes: str = ""

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "test_case_id": self.test_case_id,
            "plant_name": self.plant_name,
            "question_id": self.question_id,
            "question": self.question,
            "attribute_identifier": self.attribute_identifier,
            "expected_fact": self.expected_fact,
            "subject_node_label": self.subject_node_label,
            "subject_node_id": self.subject_node_id,
            "relationship_path": self.relationship_path,
            "target_node_label": self.target_node_label,
            "target_node_id": self.target_node_id,
            "source": self.source or "",
            "source_url": self.source_url or "",
            "verified": self.verified,
            "review_notes": self.review_notes,
        }

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class GroundTruthCase:
    test_case_id: str
    plant_name: str
    question_id: str
    question: str
    identifier: list[str]
    expected_facts: list[dict[str, Any]] = field(default_factory=list)
    expected_graph_paths: list[str] = field(default_factory=list)
    ground_truth_status: str = "VERIFIED"
    extraction_errors: list[str] = field(default_factory=list)
    review_notes: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_csv_dict(self) -> dict[str, Any]:
        summary = "; ".join(
            f["expected_fact"] for f in self.expected_facts[:5]
        )
        if len(self.expected_facts) > 5:
            summary += f" ... (+{len(self.expected_facts) - 5} more)"
        return {
            "test_case_id": self.test_case_id,
            "plant_name": self.plant_name,
            "question_id": self.question_id,
            "question": self.question,
            "identifier": json.dumps(self.identifier),
            "ground_truth_status": self.ground_truth_status,
            "fact_count": len(self.expected_facts),
            "expected_facts_summary": summary,
            "extraction_notes": "; ".join(self.extraction_errors) if self.extraction_errors else self.review_notes,
        }


# ============================================================================
# Neo4j Schema Introspection
# ============================================================================

async def introspect_neo4j_schema(client: Neo4jClient) -> dict[str, Any]:
    """Introspect running Neo4j database: labels, properties, relationships, and paths."""
    schema_info: dict[str, Any] = {
        "timestamp": utc_iso_now(),
        "labels": {},
        "relationships": [],
        "constraints": [],
        "indexes": [],
    }

    async with client.transaction() as tx:
        labels_rows = await tx.records("CALL db.labels() YIELD label RETURN label ORDER BY label")
        labels = [r["label"] for r in labels_rows]

        for l in labels:
            count = await tx.scalar(f"MATCH (n:`{l}`) RETURN count(n) AS c")
            prop_rows = await tx.records(f"""
                MATCH (n:`{l}`)
                UNWIND keys(n) AS k
                RETURN DISTINCT k ORDER BY k
            """)
            props = [r["k"] for r in prop_rows]
            schema_info["labels"][l] = {
                "node_count": count,
                "properties": props,
            }

        rel_patterns = await tx.records("""
            MATCH (a)-[r]->(b)
            RETURN head(labels(a)) AS source_label, type(r) AS relationship_type, head(labels(b)) AS target_label, count(*) AS count
            ORDER BY source_label, relationship_type, target_label
        """)
        for p in rel_patterns:
            schema_info["relationships"].append({
                "source": p["source_label"],
                "type": p["relationship_type"],
                "target": p["target_label"],
                "count": p["count"],
            })

    return schema_info


# ============================================================================
# Question-Specific Fact Extractors
# ============================================================================

class GroundTruthExtractor:
    """Extracts expected facts from Neo4j for each plant-question pair."""

    def __init__(self, client: Neo4jClient) -> None:
        self.client = client

    async def extract_for_case(
        self,
        test_case_id: str,
        plant_name: str,
        question_id: str,
        question: str,
        identifiers: list[str],
    ) -> GroundTruthCase:
        """Execute the appropriate parameterized extractor for this question."""
        case = GroundTruthCase(
            test_case_id=test_case_id,
            plant_name=plant_name,
            question_id=question_id,
            question=question,
            identifier=identifiers,
        )

        try:
            facts, paths, notes = await self._dispatch_extractor(
                test_case_id=test_case_id,
                plant_name=plant_name,
                question_id=question_id,
                question=question,
                identifiers=identifiers,
            )
            case.expected_facts = [f.to_json_dict() for f in facts]
            case.expected_graph_paths = paths
            case.review_notes = notes

            # Assign Status
            if not facts:
                case.ground_truth_status = "NO_MATCHING_GRAPH_EVIDENCE"
                if not case.review_notes:
                    case.review_notes = "Graph query executed successfully but yielded no matching records."
            else:
                # Check for partial completeness of requested identifier attributes
                all_attributes_present = True
                for f in facts:
                    rec = f.record
                    for ident in identifiers:
                        if ident not in rec or rec[ident] is None or rec[ident] == "":
                            # Check if the identifier is stored in child/parent or represented
                            if ident not in ("plant_name", "normalized_value_nm"):
                                all_attributes_present = False
                                break
                if all_attributes_present:
                    case.ground_truth_status = "VERIFIED"
                else:
                    case.ground_truth_status = "PARTIAL"

        except GraphDatabaseError as gdb_err:
            logger.warning("Graph database error for %s (%s): %s", plant_name, question_id, gdb_err)
            case.ground_truth_status = "QUERY_ERROR"
            case.extraction_errors.append(f"GraphDatabaseError: {gdb_err}")
        except Exception as exc:
            logger.exception("Unexpected error extracting ground truth for %s (%s)", plant_name, question_id)
            case.ground_truth_status = "QUERY_ERROR"
            case.extraction_errors.append(f"{type(exc).__name__}: {exc}")

        return case

    async def _dispatch_extractor(
        self,
        test_case_id: str,
        plant_name: str,
        question_id: str,
        question: str,
        identifiers: list[str],
    ) -> tuple[list[ExpectedFact], list[str], str]:
        """Dispatch question to specific extraction handler based on question_id / identifiers."""
        # Dispatch primarily by question_id when known, else by exact identifier set
        if question_id == "Q01" or (identifiers == ["phytochemical_name"]):
            return await self._extract_phytochemical_names(test_case_id, plant_name, question_id, question)

        if question_id == "Q02" or ("classyfire_kingdom" in identifiers):
            return await self._extract_phytochemical_classyfire(test_case_id, plant_name, question_id, question)

        if question_id == "Q03" or ("smiles" in identifiers and "inchi_key" in identifiers):
            return await self._extract_phytochemical_structures(test_case_id, plant_name, question_id, question)

        if question_id == "Q04" or ("chembl_id" in identifiers and "imppat_id" in identifiers):
            return await self._extract_phytochemical_ids(test_case_id, plant_name, question_id, question)

        if question_id == "Q05" or (identifiers == ["therapeutic_use"]):
            return await self._extract_therapeutic_uses(test_case_id, plant_name, question_id, question)

        if question_id == "Q06" or ("leaf" in question.lower() or "leaves" in question.lower()):
            return await self._extract_leaf_therapeutic_uses(test_case_id, plant_name, question_id, question)

        if question_id == "Q07" or ("mesh_category" in identifiers and "mesh_category_name" in identifiers):
            return await self._extract_therapeutic_mesh_categories(test_case_id, plant_name, question_id, question)

        if question_id == "Q08" or (set(identifiers) == {"therapeutic_use", "plant_part"}):
            return await self._extract_part_therapeutic_associations(test_case_id, plant_name, question_id, question)

        if question_id == "Q20" or ("target_name" in identifiers and "standard_type" in identifiers and "phytochemical_name" in identifiers):
            return await self._extract_compound_target_bioactivity_comprehensive(test_case_id, plant_name, question_id, question)

        if question_id == "Q09" or ("standard_type" in identifiers and "normalized_value_nm" in identifiers and "phytochemical_name" in identifiers):
            return await self._extract_bioactivity_measurements(test_case_id, plant_name, question_id, question)

        if question_id == "Q10" or (identifiers == ["standard_type"]):
            return await self._extract_bioactivity_types(test_case_id, plant_name, question_id, question)

        if question_id == "Q11" or (set(identifiers) == {"standard_value", "standard_relation", "standard_units"}):
            return await self._extract_bioactivity_values_units(test_case_id, plant_name, question_id, question)

        if question_id == "Q12" or ("high_confidence_tier" in identifiers):
            return await self._extract_bioactivity_high_confidence(test_case_id, plant_name, question_id, question)

        if question_id == "Q13" or (set(identifiers) == {"phytochemical_name", "target_name"}):
            return await self._extract_compound_protein_targets(test_case_id, plant_name, question_id, question)

        if question_id == "Q14" or ("target_organism" in identifiers and "target_type" in identifiers):
            return await self._extract_target_organism_type(test_case_id, plant_name, question_id, question)

        if question_id == "Q15" or ("uniprot_id" in identifiers and "target_chembl_id" in identifiers):
            return await self._extract_target_ids(test_case_id, plant_name, question_id, question)

        if question_id == "Q16" or (set(identifiers) == {"alias", "normalized_alias"}):
            return await self._extract_plant_aliases(test_case_id, plant_name, question_id, question)

        if question_id == "Q17" or ("alias_type" in identifiers and "language" in identifiers):
            return await self._extract_plant_alias_details(test_case_id, plant_name, question_id, question)

        if question_id == "Q18" or (identifiers == ["plant_part"]):
            return await self._extract_documented_plant_parts(test_case_id, plant_name, question_id, question)

        if question_id == "Q19" or (set(identifiers) == {"plant_part", "phytochemical_name", "therapeutic_use"}):
            return await self._extract_part_compound_use_triplets(test_case_id, plant_name, question_id, question)

        # Fallback for unexpected schema
        return [], [], f"Schema unsupported or unknown question identifier mapping: {identifiers}"

    # ------------------------------------------------------------------------
    # Individual question query methods
    # ------------------------------------------------------------------------

    async def _extract_phytochemical_names(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:CONTAINS]->(c:Phytochemicals)
            RETURN DISTINCT
                c.phytochemical_name AS canonical_val,
                properties(c) AS rec,
                c.inchi_key AS target_id,
                part.plant_name AS subject_id,
                c.source AS src,
                c.source_url AS src_url
            ORDER BY canonical_val
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            val = r["canonical_val"] or ""
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="phytochemical_name",
                    expected_fact=val,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->CONTAINS",
                    target_node_label="Phytochemicals",
                    target_node_id=r["target_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} phytochemical names."

    async def _extract_phytochemical_classyfire(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:CONTAINS]->(c:Phytochemicals)
            RETURN DISTINCT
                c.phytochemical_name AS name,
                c.classyfire_kingdom AS kingdom,
                c.classyfire_superclass AS superclass,
                c.classyfire_class AS clazz,
                c.classyfire_subclass AS subclass,
                properties(c) AS rec,
                c.inchi_key AS target_id,
                c.source AS src,
                c.source_url AS src_url
            ORDER BY name
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            name = r["name"] or ""
            k = r["kingdom"] or "Unknown"
            sc = r["superclass"] or "Unknown"
            cl = r["clazz"] or "Unknown"
            sub = r["subclass"] or "Unknown"
            formatted = f"{name}: {k} > {sc} > {cl} > {sub}"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="phytochemical_name, classyfire_kingdom, classyfire_superclass, classyfire_class, classyfire_subclass",
                    expected_fact=formatted,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->CONTAINS",
                    target_node_label="Phytochemicals",
                    target_node_id=r["target_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} chemical classification records."

    async def _extract_phytochemical_structures(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:CONTAINS]->(c:Phytochemicals)
            RETURN DISTINCT
                c.phytochemical_name AS name,
                c.smiles AS smiles,
                c.inchi_key AS inchi_key,
                properties(c) AS rec,
                c.source AS src,
                c.source_url AS src_url
            ORDER BY name
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            name = r["name"] or ""
            smiles = r["smiles"] or "NA"
            inchi = r["inchi_key"] or "NA"
            formatted = f"{name} (InChIKey: {inchi}, SMILES: {smiles})"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="phytochemical_name, smiles, inchi_key",
                    expected_fact=formatted,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->CONTAINS",
                    target_node_label="Phytochemicals",
                    target_node_id=inchi,
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} structural representation records."

    async def _extract_phytochemical_ids(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:CONTAINS]->(c:Phytochemicals)
            RETURN DISTINCT
                c.phytochemical_name AS name,
                c.chembl_id AS chembl_id,
                c.imppat_id AS imppat_id,
                c.inchi_key AS inchi_key,
                properties(c) AS rec,
                c.source AS src,
                c.source_url AS src_url
            ORDER BY name
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            name = r["name"] or ""
            cid = r["chembl_id"] or "NA"
            iid = r["imppat_id"] or "NA"
            formatted = f"{name} (ChEMBL: {cid}, IMPPAT: {iid})"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="phytochemical_name, chembl_id, imppat_id",
                    expected_fact=formatted,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->CONTAINS",
                    target_node_label="Phytochemicals",
                    target_node_id=r["inchi_key"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} external identifier records."

    async def _extract_therapeutic_uses(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:USED_FOR]->(u:TherapeuticUse)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:USED_FOR]->(u:TherapeuticUse)
            RETURN DISTINCT
                u.therapeutic_use AS use,
                u.mesh_id AS mesh_id,
                properties(u) AS rec,
                u.source AS src,
                u.source_url AS src_url
            ORDER BY use
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            use = r["use"] or ""
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="therapeutic_use",
                    expected_fact=use,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->USED_FOR",
                    target_node_label="TherapeuticUse",
                    target_node_id=r["mesh_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} distinct plant therapeutic uses."

    async def _extract_leaf_therapeutic_uses(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        """Leaf-specific extraction strictly enforcing verified leaf graph path."""
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:USED_FOR]->(u:TherapeuticUse) WHERE toLower(part.plant_part) IN ['leaf', 'leaves']"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:USED_FOR]->(u:TherapeuticUse)
            WHERE toLower(part.plant_part) IN ['leaf', 'leaves']
            RETURN DISTINCT
                u.therapeutic_use AS use,
                part.plant_part AS part_name,
                part.plant_part_id AS part_id,
                u.mesh_id AS mesh_id,
                properties(u) AS use_rec,
                properties(part) AS part_rec,
                u.source AS src,
                u.source_url AS src_url
            ORDER BY use
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            use = r["use"] or ""
            part_name = r["part_name"] or "leaf"
            combined_rec = {
                "plant_part": part_name,
                "plant_part_id": r["part_id"],
                "therapeutic_use": use,
                "mesh_id": r["mesh_id"],
                "source": r["src"],
                "source_url": r["src_url"],
            }
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="plant_part, therapeutic_use",
                    expected_fact=f"{part_name}: {use}",
                    record=combined_rec,
                    subject_node_label="PlantPart",
                    subject_node_id=r["part_id"] or "",
                    relationship_path="HAS_PART->USED_FOR[leaf_scoped]",
                    target_node_label="TherapeuticUse",
                    target_node_id=r["mesh_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )

        note = f"Extracted {len(facts)} verified leaf-specific therapeutic uses."
        if not facts:
            note += " Confirmed: No leaf-specific therapeutic uses exist in graph for this plant."
        return facts, [path], note

    async def _extract_therapeutic_mesh_categories(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:USED_FOR]->(u:TherapeuticUse)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:USED_FOR]->(u:TherapeuticUse)
            RETURN DISTINCT
                u.therapeutic_use AS use,
                u.mesh_category AS cat,
                u.mesh_category_name AS cat_name,
                u.mesh_sub_category_name AS sub_name,
                u.mesh_id AS mesh_id,
                properties(u) AS rec,
                u.source AS src,
                u.source_url AS src_url
            ORDER BY use
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            use = r["use"] or ""
            cat = r["cat"] or "NA"
            cat_name = r["cat_name"] or "NA"
            sub = r["sub_name"] or "NA"
            formatted = f"{use} (Category {cat}: {cat_name} / {sub})"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="therapeutic_use, mesh_category, mesh_category_name, mesh_sub_category_name",
                    expected_fact=formatted,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->USED_FOR",
                    target_node_label="TherapeuticUse",
                    target_node_id=r["mesh_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} categorized therapeutic uses."

    async def _extract_part_therapeutic_associations(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:USED_FOR]->(u:TherapeuticUse)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)-[:USED_FOR]->(u:TherapeuticUse)
            RETURN DISTINCT
                part.plant_part AS part_name,
                part.plant_part_id AS part_id,
                u.therapeutic_use AS use,
                u.mesh_id AS mesh_id,
                properties(u) AS rec,
                part.source AS src,
                part.source_url AS src_url
            ORDER BY part_name, use
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            part_name = r["part_name"] or ""
            use = r["use"] or ""
            formatted = f"{use} -> {part_name}"
            combined_rec = {
                "plant_part": part_name,
                "plant_part_id": r["part_id"],
                "therapeutic_use": use,
                "mesh_id": r["mesh_id"],
            }
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="therapeutic_use, plant_part",
                    expected_fact=formatted,
                    record=combined_rec,
                    subject_node_label="PlantPart",
                    subject_node_id=r["part_id"] or "",
                    relationship_path="HAS_PART->USED_FOR",
                    target_node_label="TherapeuticUse",
                    target_node_id=r["mesh_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} plant part to therapeutic use associations."

    async def _extract_bioactivity_measurements(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)
            RETURN DISTINCT
                c.phytochemical_name AS compound,
                c.inchi_key AS inchi_key,
                b.bioactivity_id AS bioactivity_id,
                b.standard_type AS standard_type,
                b.standard_relation AS standard_relation,
                b.standard_value AS standard_value,
                b.standard_units AS standard_units,
                b.normalized_value_nm AS normalized_value_nm,
                properties(b) AS rec,
                b.source AS src,
                b.source_url AS src_url
            ORDER BY compound, standard_type
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            c_name = r["compound"] or ""
            stype = r["standard_type"] or ""
            rel = r["standard_relation"] or ""
            val = r["standard_value"]
            units = r["standard_units"] or ""
            norm = r["normalized_value_nm"]
            bid = r["bioactivity_id"] or ""
            formatted = f"{c_name} [{bid}]: {stype} {rel} {val} {units} (normalized: {norm} nM)"
            combined_rec = dict(r["rec"])
            combined_rec["phytochemical_name"] = c_name
            combined_rec["inchi_key"] = r["inchi_key"]
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="phytochemical_name, standard_type, standard_value, standard_relation, standard_units, normalized_value_nm",
                    expected_fact=formatted,
                    record=combined_rec,
                    subject_node_label="Phytochemicals",
                    subject_node_id=r["inchi_key"] or "",
                    relationship_path="HAS_PART->CONTAINS->HAS_BIOACTIVITY",
                    target_node_label="Bioactivity",
                    target_node_id=bid,
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} bioactivity measurement records."

    async def _extract_bioactivity_types(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)
            RETURN DISTINCT
                b.standard_type AS standard_type,
                count(b) AS count,
                collect(DISTINCT c.phytochemical_name)[..5] AS sample_compounds
            ORDER BY standard_type
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            stype = r["standard_type"] or ""
            cnt = r["count"]
            compounds = ", ".join(r["sample_compounds"])
            formatted = f"{stype} (observed in {cnt} measurements; e.g., {compounds})"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="standard_type",
                    expected_fact=formatted,
                    record={"standard_type": stype, "measurement_count": cnt, "sample_compounds": r["sample_compounds"]},
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->CONTAINS->HAS_BIOACTIVITY",
                    target_node_label="Bioactivity",
                    target_node_id=stype,
                    source="ChEMBL",
                    source_url=None,
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} distinct bioactivity measurement types."

    async def _extract_bioactivity_values_units(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)
            RETURN DISTINCT
                c.phytochemical_name AS compound,
                b.bioactivity_id AS bioactivity_id,
                b.standard_type AS standard_type,
                b.standard_relation AS relation,
                b.standard_value AS value,
                b.standard_units AS units,
                properties(b) AS rec,
                b.source AS src,
                b.source_url AS src_url
            ORDER BY compound, value
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            c_name = r["compound"] or ""
            rel = r["relation"] or ""
            val = r["value"]
            units = r["units"] or ""
            stype = r["standard_type"] or ""
            formatted = f"{c_name} ({stype}): {rel} {val} {units}"
            combined = dict(r["rec"])
            combined["phytochemical_name"] = c_name
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="standard_value, standard_relation, standard_units",
                    expected_fact=formatted,
                    record=combined,
                    subject_node_label="Phytochemicals",
                    subject_node_id=c_name,
                    relationship_path="HAS_PART->CONTAINS->HAS_BIOACTIVITY",
                    target_node_label="Bioactivity",
                    target_node_id=r["bioactivity_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} value/relation/unit bioactivity records."

    async def _extract_bioactivity_high_confidence(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity {high_confidence_tier: 'HIGH'})"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)
            WHERE toUpper(b.high_confidence_tier) = 'HIGH'
            RETURN DISTINCT
                c.phytochemical_name AS compound,
                b.bioactivity_id AS bioactivity_id,
                b.high_confidence_tier AS tier,
                b.standard_type AS standard_type,
                b.standard_value AS standard_value,
                b.standard_units AS standard_units,
                properties(b) AS rec,
                b.source AS src,
                b.source_url AS src_url
            ORDER BY bioactivity_id
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            bid = r["bioactivity_id"] or ""
            tier = r["tier"] or ""
            c_name = r["compound"] or ""
            stype = r["standard_type"] or ""
            val = r["standard_value"]
            units = r["standard_units"] or ""
            formatted = f"{bid} (Tier: {tier}) - {c_name}: {stype} {val} {units}"
            combined = dict(r["rec"])
            combined["phytochemical_name"] = c_name
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="high_confidence_tier, bioactivity_id",
                    expected_fact=formatted,
                    record=combined,
                    subject_node_label="Phytochemicals",
                    subject_node_id=c_name,
                    relationship_path="HAS_PART->CONTAINS->HAS_BIOACTIVITY[HIGH]",
                    target_node_label="Bioactivity",
                    target_node_id=bid,
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} high-confidence bioactivity records."

    async def _extract_compound_protein_targets(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)
            RETURN DISTINCT
                c.phytochemical_name AS compound,
                c.inchi_key AS inchi_key,
                t.target_name AS target,
                t.uniprot_id AS uniprot_id,
                t.target_chembl_id AS chembl_id,
                properties(t) AS rec,
                t.source AS src,
                coalesce(t.uniprot_url, t.chembl_url) AS src_url
            ORDER BY compound, target
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            c_name = r["compound"] or ""
            target = r["target"] or ""
            formatted = f"{c_name} -> {target}"
            combined = dict(r["rec"])
            combined["phytochemical_name"] = c_name
            combined["inchi_key"] = r["inchi_key"]
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="phytochemical_name, target_name",
                    expected_fact=formatted,
                    record=combined,
                    subject_node_label="Phytochemicals",
                    subject_node_id=r["inchi_key"] or "",
                    relationship_path="HAS_PART->CONTAINS->HAS_BIOACTIVITY->MEASURED_ON",
                    target_node_label="Protein_Target",
                    target_node_id=r["uniprot_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} compound to protein target associations."

    async def _extract_target_organism_type(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(:Phytochemicals)-[:HAS_BIOACTIVITY]->(:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(:Phytochemicals)-[:HAS_BIOACTIVITY]->(:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)
            RETURN DISTINCT
                t.target_name AS target,
                t.target_organism AS organism,
                t.target_type AS target_type,
                t.uniprot_id AS uniprot_id,
                properties(t) AS rec,
                t.source AS src,
                coalesce(t.uniprot_url, t.chembl_url) AS src_url
            ORDER BY target
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            target = r["target"] or ""
            org = r["organism"] or "Unknown organism"
            ttype = r["target_type"] or "Unknown type"
            formatted = f"{target} (Organism: {org}, Type: {ttype})"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="target_name, target_organism, target_type",
                    expected_fact=formatted,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->CONTAINS->HAS_BIOACTIVITY->MEASURED_ON",
                    target_node_label="Protein_Target",
                    target_node_id=r["uniprot_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} protein target organism and type records."

    async def _extract_target_ids(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(:Phytochemicals)-[:HAS_BIOACTIVITY]->(:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(:Phytochemicals)-[:HAS_BIOACTIVITY]->(:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)
            RETURN DISTINCT
                t.target_name AS target,
                t.uniprot_id AS uniprot_id,
                t.target_chembl_id AS chembl_id,
                properties(t) AS rec,
                t.source AS src,
                coalesce(t.uniprot_url, t.chembl_url) AS src_url
            ORDER BY target
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            target = r["target"] or ""
            uid = r["uniprot_id"] or "NA"
            cid = r["chembl_id"] or "NA"
            formatted = f"{target} (UniProt: {uid}, ChEMBL: {cid})"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="target_name, uniprot_id, target_chembl_id",
                    expected_fact=formatted,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART->CONTAINS->HAS_BIOACTIVITY->MEASURED_ON",
                    target_node_label="Protein_Target",
                    target_node_id=uid,
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} protein target external identifier records."

    async def _extract_plant_aliases(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_ALIAS]->(a:PlantAlias)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_ALIAS]->(a:PlantAlias)
            RETURN DISTINCT
                a.alias AS alias,
                a.normalized_alias AS norm_alias,
                properties(a) AS rec,
                a.language AS lang,
                a.alias_type AS atype,
                p.source AS src,
                p.biodiversity_url AS src_url
            ORDER BY alias
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            alias = r["alias"] or ""
            norm = r["norm_alias"] or ""
            formatted = f"{alias} (normalized: {norm})"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="alias, normalized_alias",
                    expected_fact=formatted,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_ALIAS",
                    target_node_label="PlantAlias",
                    target_node_id=norm,
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} plant alias records."

    async def _extract_plant_alias_details(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_ALIAS]->(a:PlantAlias)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_ALIAS]->(a:PlantAlias)
            RETURN DISTINCT
                a.alias AS alias,
                a.alias_type AS alias_type,
                a.language AS language,
                a.normalized_alias AS norm_alias,
                properties(a) AS rec,
                p.source AS src,
                p.biodiversity_url AS src_url
            ORDER BY alias
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            alias = r["alias"] or ""
            atype = r["alias_type"] or "Unknown"
            lang = r["language"] or "Unknown"
            formatted = f"{alias} (Type: {atype}, Language: {lang})"
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="alias, alias_type, language",
                    expected_fact=formatted,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_ALIAS",
                    target_node_label="PlantAlias",
                    target_node_id=r["norm_alias"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} alias metadata records."

    async def _extract_documented_plant_parts(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)
            RETURN DISTINCT
                part.plant_part AS part_name,
                part.plant_part_id AS part_id,
                properties(part) AS rec,
                part.source AS src,
                part.source_url AS src_url
            ORDER BY part_name
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            pname = r["part_name"] or ""
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="plant_part",
                    expected_fact=pname,
                    record=r["rec"],
                    subject_node_label="PlantDetails",
                    subject_node_id=plant_name,
                    relationship_path="HAS_PART",
                    target_node_label="PlantPart",
                    target_node_id=r["part_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} documented plant parts."

    async def _extract_part_compound_use_triplets(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart); (part)-[:CONTAINS]->(c:Phytochemicals); (part)-[:USED_FOR]->(u:TherapeuticUse)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)
            MATCH (part)-[:CONTAINS]->(c:Phytochemicals)
            MATCH (part)-[:USED_FOR]->(u:TherapeuticUse)
            RETURN DISTINCT
                part.plant_part AS part_name,
                part.plant_part_id AS part_id,
                c.phytochemical_name AS compound,
                c.inchi_key AS inchi_key,
                u.therapeutic_use AS use,
                u.mesh_id AS mesh_id,
                part.source AS src,
                part.source_url AS src_url
            ORDER BY part_name, compound, use
            LIMIT 1000
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            pname = r["part_name"] or ""
            comp = r["compound"] or ""
            use = r["use"] or ""
            formatted = f"{pname}: contains {comp}, used for {use}"
            combined = {
                "plant_part": pname,
                "plant_part_id": r["part_id"],
                "phytochemical_name": comp,
                "inchi_key": r["inchi_key"],
                "therapeutic_use": use,
                "mesh_id": r["mesh_id"],
            }
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="plant_part, phytochemical_name, therapeutic_use",
                    expected_fact=formatted,
                    record=combined,
                    subject_node_label="PlantPart",
                    subject_node_id=r["part_id"] or "",
                    relationship_path="PlantPart(-CONTAINS->Phytochemicals, -USED_FOR->TherapeuticUse)",
                    target_node_label="PlantPart",
                    target_node_id=r["part_id"] or "",
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} part-compound-use triplets."

    async def _extract_compound_target_bioactivity_comprehensive(
        self, test_case_id: str, plant_name: str, question_id: str, question: str
    ) -> tuple[list[ExpectedFact], list[str], str]:
        path = "(:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)"
        cypher = """
            MATCH (p:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(b:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)
            RETURN DISTINCT
                c.phytochemical_name AS compound,
                c.inchi_key AS inchi_key,
                t.target_name AS target,
                t.uniprot_id AS uniprot_id,
                b.bioactivity_id AS bioactivity_id,
                b.standard_type AS standard_type,
                b.standard_relation AS standard_relation,
                b.standard_value AS standard_value,
                b.standard_units AS standard_units,
                b.normalized_value_nm AS normalized_value_nm,
                properties(b) AS rec,
                b.source AS src,
                b.source_url AS src_url
            ORDER BY compound, target, standard_type
        """
        async with self.client.transaction() as tx:
            rows = await tx.records(cypher, {"plant_name": plant_name})

        facts: list[ExpectedFact] = []
        for idx, r in enumerate(rows, 1):
            comp = r["compound"] or ""
            target = r["target"] or ""
            stype = r["standard_type"] or ""
            rel = r["standard_relation"] or ""
            val = r["standard_value"]
            units = r["standard_units"] or ""
            norm = r["normalized_value_nm"]
            bid = r["bioactivity_id"] or ""
            formatted = f"{comp} -> {target}: {stype} {rel} {val} {units} (normalized: {norm} nM) [{bid}]"
            combined = dict(r["rec"])
            combined["phytochemical_name"] = comp
            combined["inchi_key"] = r["inchi_key"]
            combined["target_name"] = target
            combined["uniprot_id"] = r["uniprot_id"]
            facts.append(
                ExpectedFact(
                    fact_id=f"FACT_{test_case_id}_{idx:03d}",
                    test_case_id=test_case_id,
                    plant_name=plant_name,
                    question_id=question_id,
                    question=question,
                    attribute_identifier="phytochemical_name, target_name, standard_type, standard_value, standard_relation, standard_units, normalized_value_nm",
                    expected_fact=formatted,
                    record=combined,
                    subject_node_label="Phytochemicals",
                    subject_node_id=r["inchi_key"] or "",
                    relationship_path="HAS_PART->CONTAINS->HAS_BIOACTIVITY->MEASURED_ON",
                    target_node_label="Bioactivity",
                    target_node_id=bid,
                    source=r["src"],
                    source_url=r["src_url"],
                    verified=True,
                )
            )
        return facts, [path], f"Extracted {len(facts)} comprehensive compound-target-bioactivity records."


# ============================================================================
# Generation Workflow and CLI
# ============================================================================

async def generate_ground_truth(
    questions_file: Path,
    plants_file: Path,
    output_dir: Path,
    target_plant: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    overwrite: bool = False,
    schema_only: bool = False,
) -> dict[str, Any]:
    """Execute ground-truth generation pipeline."""
    # Check output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_jsonl_path = output_dir / "ground_truth_cases.jsonl"
    facts_csv_path = output_dir / "ground_truth_facts.csv"
    cases_csv_path = output_dir / "ground_truth_cases.csv"
    schema_json_path = output_dir / "neo4j_schema_inventory.json"
    report_json_path = output_dir / "ground_truth_report.json"

    if not overwrite and not schema_only:
        existing = [p for p in [cases_jsonl_path, facts_csv_path, cases_csv_path, report_json_path] if p.exists()]
        if existing:
            raise FileExistsError(
                f"Output files already exist in {output_dir}: {[p.name for p in existing]}. Pass --overwrite to replace them."
            )

    # Load Neo4j connection
    config = load_neo4j_config()
    conn = Neo4jConnection(config)
    await conn.open()
    client = Neo4jClient(conn)

    try:
        # 1. Introspect schema
        logger.info("Introspecting Neo4j schema...")
        schema_inventory = await introspect_neo4j_schema(client)
        with open(schema_json_path, "w", encoding="utf-8") as f:
            json.dump(schema_inventory, f, indent=2)
        logger.info("Saved schema inventory to %s", schema_json_path)

        if schema_only:
            logger.info("Schema-only mode requested. Done.")
            return {"status": "SCHEMA_ONLY", "schema": schema_inventory}

        # 2. Load Questions and Plants
        logger.info("Loading questions from %s", questions_file)
        raw_questions = load_xlsx_records(questions_file)
        logger.info("Loaded %d questions from xlsx", len(raw_questions))

        logger.info("Loading plant names from %s", plants_file)
        with open(plants_file, "r", encoding="utf-8") as f:
            plant_data = json.load(f)
        all_plants = [p["plant_name"].strip() for p in plant_data if p.get("plant_name")]
        logger.info("Loaded %d plant names from json", len(all_plants))

        if target_plant:
            target_norm = normalize_text(target_plant).lower()
            matching_plants = [p for p in all_plants if normalize_text(p).lower() == target_norm]
            if not matching_plants:
                # Allow plant even if not in plant_names.json if requested specifically
                all_plants = [target_plant]
            else:
                all_plants = matching_plants
            logger.info("Filtered to target plant: %s", all_plants)

        # 3. Build test case pairs
        all_pairs: list[dict[str, Any]] = []
        for p_idx, plant in enumerate(all_plants, 1):
            for q_idx, q_row in enumerate(raw_questions, 1):
                question_text = q_row.get("question", "").strip()
                raw_ident = q_row.get("identifier", "[]")
                ident_list = parse_identifier_list(raw_ident)
                qid = f"Q{q_idx:02d}"
                test_case_id = f"TC_{slugify(plant)}_{qid}"
                all_pairs.append({
                    "test_case_id": test_case_id,
                    "plant_name": plant,
                    "question_id": qid,
                    "question": question_text,
                    "identifiers": ident_list,
                })

        total_expected_pairs = len(all_plants) * len(raw_questions)
        logger.info("Total generated plant-question pairs: %d", len(all_pairs))

        # Apply offset and limit
        if offset > 0:
            all_pairs = all_pairs[offset:]
        if limit is not None and limit > 0:
            all_pairs = all_pairs[:limit]

        logger.info("Processing %d cases after offset/limit...", len(all_pairs))

        extractor = GroundTruthExtractor(client)
        cases: list[GroundTruthCase] = []
        all_facts: list[ExpectedFact] = []

        status_counts: dict[str, int] = {}
        counts_by_ident: dict[str, int] = {}
        counts_by_plant: dict[str, int] = {}

        t0 = datetime.now(timezone.utc)
        for i, pair in enumerate(all_pairs, 1):
            if i % 50 == 0 or i == 1 or i == len(all_pairs):
                logger.info("Progress: %d / %d cases processed", i, len(all_pairs))

            case = await extractor.extract_for_case(
                test_case_id=pair["test_case_id"],
                plant_name=pair["plant_name"],
                question_id=pair["question_id"],
                question=pair["question"],
                identifiers=pair["identifiers"],
            )
            cases.append(case)

            # Reconstruct ExpectedFact objects for CSV output
            for f_dict in case.expected_facts:
                fact_obj = ExpectedFact(
                    fact_id=f_dict["fact_id"],
                    test_case_id=f_dict["test_case_id"],
                    plant_name=f_dict["plant_name"],
                    question_id=f_dict["question_id"],
                    question=f_dict["question"],
                    attribute_identifier=f_dict["attribute_identifier"],
                    expected_fact=f_dict["expected_fact"],
                    record=f_dict.get("record", {}),
                    subject_node_label=f_dict.get("subject_node_label", ""),
                    subject_node_id=f_dict.get("subject_node_id", ""),
                    relationship_path=f_dict.get("relationship_path", ""),
                    target_node_label=f_dict.get("target_node_label", ""),
                    target_node_id=f_dict.get("target_node_id", ""),
                    source=f_dict.get("source"),
                    source_url=f_dict.get("source_url"),
                    verified=f_dict.get("verified", True),
                    review_notes=f_dict.get("review_notes", ""),
                )
                all_facts.append(fact_obj)

            # Counters
            status_counts[case.ground_truth_status] = status_counts.get(case.ground_truth_status, 0) + 1
            ident_key = ", ".join(pair["identifiers"])
            counts_by_ident[ident_key] = counts_by_ident.get(ident_key, 0) + len(case.expected_facts)
            counts_by_plant[pair["plant_name"]] = counts_by_plant.get(pair["plant_name"], 0) + len(case.expected_facts)

        t1 = datetime.now(timezone.utc)
        elapsed_sec = (t1 - t0).total_seconds()
        logger.info("Extraction finished in %.2f seconds.", elapsed_sec)

        # 4. Write ground_truth_cases.jsonl
        logger.info("Writing %s ...", cases_jsonl_path)
        with open(cases_jsonl_path, "w", encoding="utf-8") as f:
            for c in cases:
                f.write(json.dumps(c.to_json_dict(), ensure_ascii=False) + "\n")

        # 5. Write ground_truth_facts.csv
        logger.info("Writing %s ...", facts_csv_path)
        fact_fieldnames = [
            "fact_id", "test_case_id", "plant_name", "question_id", "question",
            "attribute_identifier", "expected_fact", "subject_node_label",
            "subject_node_id", "relationship_path", "target_node_label",
            "target_node_id", "source", "source_url", "verified", "review_notes"
        ]
        with open(facts_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fact_fieldnames)
            writer.writeheader()
            for fact in all_facts:
                writer.writerow(fact.to_csv_dict())

        # 6. Write ground_truth_cases.csv
        logger.info("Writing %s ...", cases_csv_path)
        case_fieldnames = [
            "test_case_id", "plant_name", "question_id", "question",
            "identifier", "ground_truth_status", "fact_count",
            "expected_facts_summary", "extraction_notes"
        ]
        with open(cases_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=case_fieldnames)
            writer.writeheader()
            for c in cases:
                writer.writerow(c.to_csv_dict())

        # 7. Write ground_truth_report.json
        report: dict[str, Any] = {
            "timestamp": utc_iso_now(),
            "elapsed_seconds": round(elapsed_sec, 2),
            "input_plant_count": len(all_plants),
            "input_question_count": len(raw_questions),
            "expected_total_cases": total_expected_pairs,
            "processed_cases": len(cases),
            "total_expected_facts": len(all_facts),
            "status_counts": status_counts,
            "zero_evidence_cases_count": status_counts.get("NO_MATCHING_GRAPH_EVIDENCE", 0),
            "query_error_cases_count": status_counts.get("QUERY_ERROR", 0),
            "counts_by_identifier": counts_by_ident,
            "counts_by_plant": counts_by_plant,
            "notes": (
                "Ground truth extracted strictly from live Neo4j database using verified relationship paths. "
                "Plant-part scope (e.g. leaf questions) is strictly enforced via leaf-specific relationship paths. "
                "No agent answers or model outputs were used as ground truth."
            ),
        }

        with open(report_json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info("Saved report to %s", report_json_path)

        return report

    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate verified ground truth from Neo4j database.")
    parser.add_argument(
        "--questions",
        "-q",
        type=Path,
        default=Path("evaluation-job-1/test_data.xlsx"),
        help="Path to questions file (.xlsx)",
    )
    parser.add_argument(
        "--plants",
        "-p",
        type=Path,
        default=Path("evaluation-job-1/plant_names.json"),
        help="Path to plant names JSON file",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("data/ground_truth"),
        help="Directory to save ground-truth files",
    )
    parser.add_argument(
        "--plant",
        type=str,
        default=None,
        help="Filter extraction to a single canonical plant name (e.g., 'Basella alba')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of cases to process",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Offset start of cases to process",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files if present",
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Introspect and save Neo4j schema inventory only, without extracting cases",
    )

    args = parser.parse_args()

    asyncio.run(
        generate_ground_truth(
            questions_file=args.questions,
            plants_file=args.plants,
            output_dir=args.output_dir,
            target_plant=args.plant,
            limit=args.limit,
            offset=args.offset,
            overwrite=args.overwrite,
            schema_only=args.schema_only,
        )
    )


if __name__ == "__main__":
    main()
