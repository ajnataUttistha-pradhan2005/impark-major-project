"""Read-only, bounded explanatory notes imported from authoritative vocabularies."""

import json
import re
from uuid import NAMESPACE_URL, uuid5

from backend.contracts.evidence import Evidence, EvidenceClass, Modality, Provenance
from backend.contracts.response import ResponseContext
from backend.database.postgres.client import PostgresClient

MESH_ID = re.compile(r"D\d{6,9}\Z")


class ReferenceNotes:
    def __init__(self, database: PostgresClient) -> None:
        self.database = database

    async def for_context(self, context: ResponseContext) -> list[Evidence]:
        ids: dict[str, str] = {}
        for evidence in context.graph_evidence[:20]:
            if evidence.provenance.reference.partition(":")[0] != "GET_THERAPEUTIC_USES":
                continue
            for node in evidence.graph_nodes:
                identifier = node.get("mesh_id")
                label = node.get("therapeutic_use")
                if (
                    isinstance(identifier, str)
                    and MESH_ID.fullmatch(identifier)
                    and isinstance(label, str)
                ):
                    ids[identifier] = label
        if not ids:
            return []
        rows = await self.database.read(
            "SELECT external_id, label, description, source_url FROM reference_note "
            "WHERE source='mesh' AND external_id=ANY($1::text[]) LIMIT 20",
            list(ids),
        )
        notes = []
        for row in rows:
            identifier = row["external_id"]
            # A vocabulary note explains the same term, never the plant/use link.
            if row["label"].casefold() != ids.get(identifier, "").casefold():
                continue
            # MeSH uses all-caps emphasis for cross-referenced words. Normalize
            # presentation while preserving the source wording and its meaning.
            definition = re.sub(
                r"\b[A-Z]{5,}\b", lambda match: match.group().lower(), row["description"]
            )
            claim = json.dumps({"term": row["label"], "definition": definition}, ensure_ascii=False)
            notes.append(
                Evidence(
                    evidence_id=uuid5(NAMESPACE_URL, f"mesh:{identifier}:{definition}"),
                    modality=Modality.TEXT,
                    claim=claim,
                    evidence_type=EvidenceClass.UNKNOWN,
                    confidence=1,
                    source_quality=1,
                    provenance=Provenance(
                        source_id=identifier, source_type="mesh", reference="definition"
                    ),
                    supports=[identifier],
                    source_urls=[row["source_url"]],
                )
            )
        return notes
