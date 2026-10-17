"""Read-only, bounded snapshot of the one plant locked to a conversation."""

import json
from uuid import UUID

from backend.database.neo4j.client import Neo4jClient
from backend.database.postgres.client import PostgresClient

_PART = "-[:HAS_PART]->(part:PlantPart)"
_COMPOUND = _PART + "-[:CONTAINS]->(compound:Phytochemicals)"
_ACTIVITY = _COMPOUND + "-[:HAS_BIOACTIVITY]->(activity:Bioactivity)"
_PATHS: tuple[tuple[str, int], ...] = (
    ("", 1),
    ("-[:HAS_ALIAS]->(alias:PlantAlias)", 80),
    (_PART, 40),
    (_PART + "-[:USED_FOR]->(use:TherapeuticUse)", 80),
    (_COMPOUND, 100),
    (_ACTIVITY, 100),
    (_ACTIVITY + "-[:MEASURED_ON]->(target:Protein_Target)", 50),
    (_ACTIVITY + "-[:REPORTED_IN]->(document:Document)", 50),
)


class PlantContextLoader:
    def __init__(self, graph: Neo4jClient, postgres: PostgresClient) -> None:
        self.graph = graph
        self.postgres = postgres

    async def load(
        self, plant_id: str, *, max_bytes: int = 14_000
    ) -> tuple[list[dict[str, object]], bool]:
        plant_uuid = UUID(plant_id)
        name = await self.postgres.scalar(
            "SELECT p.plant_name FROM search_plant p JOIN search_generation g USING(generation) "
            "WHERE g.status='active' AND p.plant_id=$1",
            plant_uuid,
        )
        if not isinstance(name, str):
            return [], False
        context: list[dict[str, object]] = []
        used = 0
        truncated = False
        per_category = max_bytes // len(_PATHS)
        for pattern, limit in _PATHS:
            category_used = 0
            query = (
                "MATCH path=(p:PlantDetails {plant_name:$name})" + pattern
                + " RETURN [n IN nodes(path) | properties(n)] AS nodes, "
                "[r IN relationships(path) | type(r)] AS relationships "
                "LIMIT $limit"
            )
            rows = await self.graph.read(
                query, {"name": name, "limit": limit + 1}, timeout_seconds=5
            )
            if len(rows) > limit:
                truncated = True
            for row in rows[:limit]:
                nodes = row["nodes"]
                # Keep complete terminal properties and compact ancestor identity.
                compact = [
                    node if index == len(nodes) - 1 else {
                        key: node[key] for key in (
                            "plant_name", "plant_part", "phytochemical_name",
                            "bioactivity_id", "therapeutic_use", "target_name",
                        ) if key in node
                    }
                    for index, node in enumerate(nodes)
                ]
                item = {"nodes": compact, "relationships": row["relationships"]}
                size = len(json.dumps(item, default=str, ensure_ascii=False))
                if used + size > max_bytes or category_used + size > per_category:
                    truncated = True
                    break
                context.append(item)
                used += size
                category_used += size
            if used >= max_bytes:
                break
        return context, truncated
