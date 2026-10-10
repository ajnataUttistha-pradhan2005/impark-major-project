"""Explicit, read-only diagnostics. Missing privileges are reported, never inferred."""

from backend.database.neo4j.client import Neo4jClient, RecordData
from backend.database.neo4j.errors import GraphDatabaseError

CHECKS = {
    "indexes": "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, state "
    "RETURN name, type, entityType, labelsOrTypes, properties, state",
    "constraints": "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
    "RETURN name, type, entityType, labelsOrTypes, properties",
    "labels": "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY label",
    "relationships": "MATCH (s)-[r]->(t) RETURN labels(s) AS source, type(r) AS relationship, "
    "labels(t) AS target, count(*) AS count ORDER BY relationship",
}


async def inspect_database(client: Neo4jClient) -> dict[str, list[RecordData] | str]:
    result: dict[str, list[RecordData] | str] = {}
    result["server"] = [await client.server_info()]
    for name, query in CHECKS.items():
        try:
            result[name] = await client.read(query)
        except GraphDatabaseError as error:
            result[name] = f"unavailable: {error.code}"
    return result
