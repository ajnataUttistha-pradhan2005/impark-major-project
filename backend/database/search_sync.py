"""Neo4j -> PostgreSQL + Qdrant generation import; graph remains read-only."""

import json
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.agents.text.catalog import NameRecord
from backend.agents.text.embeddings import EmbeddingProvider
from backend.agents.text.resolver import normalize
from backend.database.neo4j.client import Neo4jClient
from backend.database.postgres.client import PostgresClient
from backend.database.qdrant.client import QdrantStore

ENTITY_EXPORTS = {
    "compound": (
        "MATCH (n:Phytochemicals) RETURN n.inchi_key AS id,n.phytochemical_name AS "
        "label ORDER BY id,label SKIP $offset LIMIT $limit "
    ),
    "therapeutic_use": (
        "MATCH (n:TherapeuticUse) RETURN n.mesh_id AS id,n.therapeutic_use AS label "
        "ORDER BY id,label SKIP $offset LIMIT $limit "
    ),
    "target": (
        "MATCH (n:Protein_Target) RETURN n.uniprot_id AS id,n.target_name AS label "
        "ORDER BY id,label SKIP $offset LIMIT $limit "
    ),
}


async def extract_entities(graph: Neo4jClient) -> list[tuple[str, str, str, str]]:
    entities = set()
    for kind, cypher in ENTITY_EXPORTS.items():
        for offset in range(0, 10000, 500):
            rows = await graph.read(cypher, {"offset": offset, "limit": 500})
            for row in rows:
                if isinstance(row["id"], str) and row["id"] and isinstance(row["label"], str):
                    entities.add((kind, row["id"], row["label"], normalize(row["label"])))
                    entities.add((kind, row["id"], row["id"], normalize(row["id"])))
            if len(rows) < 500:
                break
        else:
            raise ValueError("Entity catalog limit exceeded")
    return sorted(entities)


async def extract_names(graph: Neo4jClient) -> list[NameRecord]:
    plants = await graph.read(
        "MATCH (p:PlantDetails) RETURN p.plant_name AS plant_name, "
        "p.taxonomy_id AS taxonomy_id ORDER BY plant_name LIMIT 1000"
    )
    if not plants or len(plants) >= 1000:
        raise ValueError("Empty or oversized plant catalog; refusing partial import")
    names: dict[UUID, NameRecord] = {}
    seen: set[str] = set()
    for plant in plants:
        name = plant["plant_name"]
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError("Missing or duplicate canonical name; source mapping needs review")
        seen.add(name)
        # Application UUID, NOT a claimed Neo4j property; stable across Aura/local clone.
        plant_id = uuid5(NAMESPACE_URL, "impark:plant:" + name)
        rows = await graph.read(
            "MATCH (p:PlantDetails {plant_name:$name})-[:HAS_ALIAS]->(a:PlantAlias) "
            "RETURN a.alias AS alias,a.alias_type AS alias_type,a.language AS language,"
            "a.normalized_alias AS normalized_alias ORDER BY alias,language LIMIT 1000",
            {"name": name},
        )
        if len(rows) >= 1000:
            raise ValueError("Alias limit reached; refusing truncated import")
        for row in [
            {"alias": name, "alias_type": "canonical", "language": None, "normalized_alias": None},
            *rows,
        ]:
            alias = row["alias"]
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("Source alias is missing; refusing incomplete import")
            key = json.dumps([name, alias, row["alias_type"], row["language"]], ensure_ascii=False)
            identifier = uuid5(plant_id, key)
            names[identifier] = NameRecord(
                name_id=identifier,
                plant_id=plant_id,
                plant_name=name,
                name=alias,
                normalized_name=normalize(alias),
                source_normalized_alias=row["normalized_alias"],
                alias_type=row["alias_type"],
                language=row["language"],
                source_key=key,
            )
    return list(names.values())


async def populate(
    graph: Neo4jClient,
    postgres: PostgresClient,
    vectors: QdrantStore,
    embeddings: EmbeddingProvider,
) -> dict[str, str | int]:
    records = await extract_names(graph)
    entities = await extract_entities(graph)
    content = json.dumps(
        [r.model_dump(mode="json") for r in sorted(records, key=lambda r: str(r.name_id))],
        ensure_ascii=False,
        sort_keys=True,
    )
    generation = uuid5(
        NAMESPACE_URL, vectors.config.embedding_model + ":v2:" + content + str(entities)
    )
    plants = {r.plant_id: r.plant_name for r in records}
    await vectors.provision()
    active = await postgres.scalar(
        "SELECT status FROM search_generation WHERE generation=$1", generation
    )
    if active == "active" and await vectors.count(generation) == len(records):
        return {
            "generation": str(generation),
            "plants": len(plants),
            "names": len(records),
            "unchanged": 1,
        }
    async with postgres.transaction(write=True) as tx:
        await tx.execute(
            "INSERT INTO search_generation VALUES($1,now(),$2,$3,$4,'staging') "
            "ON CONFLICT(generation) DO NOTHING",
            generation,
            vectors.config.embedding_model,
            len(plants),
            len(records),
        )
        await tx.executemany(
            "INSERT INTO search_plant VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",
            [(generation, key, value, value) for key, value in plants.items()],
        )
        await tx.executemany(
            "INSERT INTO search_entity(generation,kind,entity_id,label,normalized_label) "
            "VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
            [(generation, *row) for row in entities],
        )
        await tx.executemany(
            "INSERT INTO search_name(generation,name_id,plant_id,name,normalized_name,"
            "source_normalized_alias,alias_type,language,source_key) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING",
            [
                (
                    generation,
                    r.name_id,
                    r.plant_id,
                    r.name,
                    r.normalized_name,
                    r.source_normalized_alias,
                    r.alias_type,
                    r.language,
                    r.source_key,
                )
                for r in records
            ],
        )
    # One vector per name avoids diluting a short alias in a long combined plant document.
    # Old generation stays available until every new vector is durably acknowledged.
    for start in range(0, len(records), 64):
        batch = records[start : start + 64]
        embeddings_batch = await embeddings.embed([r.name for r in batch])
        await vectors.upsert(generation, batch, embeddings_batch)
    if await vectors.count(generation) != len(records):
        raise ValueError("Vector count mismatch; previous generation remains active")
    async with postgres.transaction(write=True) as tx:
        await tx.execute("SELECT pg_advisory_xact_lock(72421002)")
        await tx.execute("UPDATE search_generation SET status='retired' WHERE status='active'")
        await tx.execute(
            "UPDATE search_generation SET status='active' WHERE generation=$1", generation
        )
    return {"generation": str(generation), "plants": len(plants), "names": len(records)}
