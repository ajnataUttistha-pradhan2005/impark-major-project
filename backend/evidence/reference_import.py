"""Explicit MeSH definition import; never runs during application startup.

Run the PostgreSQL migration first, then `python -m backend.evidence.reference_import`.
Only graph-linked descriptor IDs are fetched. No plant efficacy claim is imported.
"""

import argparse
import asyncio
import re

import httpx

from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import load_neo4j_config
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.postgres.client import PostgresClient
from backend.database.search_config import SearchSettings
from backend.evidence.reference import MESH_ID

CONCEPT_URL = re.compile(r"https?://id\.nlm\.nih\.gov/mesh/M\d{6,9}\Z")


def _literal(value: object) -> str:
    if isinstance(value, dict) and value.get("@language") == "en":
        text = value.get("@value")
        if isinstance(text, str):
            return " ".join(text.split())
    return ""


async def fetch_mesh_note(
    client: httpx.AsyncClient, identifier: str, expected: str
) -> tuple[str, str, str] | None:
    if not MESH_ID.fullmatch(identifier):
        return None
    url = f"https://id.nlm.nih.gov/mesh/{identifier}.json"
    descriptor_response = await client.get(url)
    descriptor_response.raise_for_status()
    descriptor = descriptor_response.json()
    if not isinstance(descriptor, dict) or descriptor.get("identifier") != identifier:
        return None
    label = _literal(descriptor.get("label"))
    concept = descriptor.get("preferredConcept")
    if (
        label.casefold() != expected.casefold()
        or not isinstance(concept, str)
        or not CONCEPT_URL.fullmatch(concept)
    ):
        return None
    concept_response = await client.get(concept.replace("http://", "https://") + ".json")
    concept_response.raise_for_status()
    concept_data = concept_response.json()
    if not isinstance(concept_data, dict) or concept_data.get("@id") != concept:
        return None
    definition = _literal(concept_data.get("scopeNote"))[:1200]
    if not definition or _literal(concept_data.get("label")).casefold() != label.casefold():
        return None
    return label, definition, url


async def import_notes(limit: int = 500) -> tuple[int, int]:
    settings = SearchSettings()
    database = PostgresClient(settings)
    imported = skipped = 0
    await database.open()
    try:
        async with Neo4jConnection(load_neo4j_config()) as connection:
            graph = Neo4jClient(connection)
            async with httpx.AsyncClient(timeout=8, follow_redirects=False) as http:
                offset = 0
                while offset < limit:
                    batch = min(50, limit - offset)
                    rows = await graph.read(
                        "MATCH (u:TherapeuticUse) WHERE u.mesh_id IS NOT NULL "
                        "RETURN DISTINCT u.mesh_id AS identifier, u.therapeutic_use AS label "
                        "ORDER BY identifier SKIP $skip LIMIT $limit",
                        {"skip": offset, "limit": batch},
                    )
                    if not rows:
                        break
                    offset += len(rows)
                    gate = asyncio.Semaphore(4)

                    async def retrieve(
                        row: dict[str, object],
                        limiter: asyncio.Semaphore = gate,
                    ) -> tuple[str, tuple[str, str, str] | None]:
                        identifier, label = row["identifier"], row["label"]
                        if not isinstance(identifier, str) or not isinstance(label, str):
                            return "", None
                        try:
                            async with limiter:
                                note = await fetch_mesh_note(http, identifier, label)
                        except (httpx.HTTPError, ValueError):
                            return identifier, None
                        return identifier, note

                    for identifier, note in await asyncio.gather(*(retrieve(row) for row in rows)):
                        if note is None:
                            skipped += 1
                            continue
                        title, definition, url = note
                        await database.write(
                            "INSERT INTO reference_note"
                            "(source, external_id, label, description, source_url) "
                            "VALUES('mesh',$1,$2,$3,$4) ON CONFLICT (source,external_id) "
                            "DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description, "
                            "source_url=EXCLUDED.source_url, fetched_at=now() "
                            "RETURNING external_id",
                            identifier,
                            title,
                            definition,
                            url,
                        )
                        imported += 1
                    if len(rows) < batch:
                        break
    finally:
        await database.close()
    return imported, skipped


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if not 1 <= args.limit <= 2000:
        parser.error("--limit must be 1..2000")
    print("Imported, skipped:", asyncio.run(import_notes(args.limit)))
