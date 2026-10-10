"""Explicit health/schema inspection; intentionally no seed or migration command."""

import argparse
import asyncio
import json

from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import load_neo4j_config
from backend.database.neo4j.diagnostics import inspect_database
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.neo4j.errors import GraphDatabaseError
from backend.database.neo4j.medicinal import MedicinalPlantRepository


async def run(command: str, env_file: str) -> None:
    async with Neo4jConnection(load_neo4j_config(env_file)) as connection:
        client = Neo4jClient(connection)
        if command == "health":
            print(json.dumps({"healthy": await client.health()}))
        elif command == "inspect":
            print(json.dumps(await inspect_database(client), indent=2, ensure_ascii=False))
        else:
            plants = await MedicinalPlantRepository(client).list_plants(limit=5)
            print(
                json.dumps([plant.model_dump() for plant in plants], indent=2, ensure_ascii=False)
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Neo4j diagnostics")
    parser.add_argument("command", choices=["health", "inspect", "plants"])
    parser.add_argument("--env-file", default=".env")
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments.command, arguments.env_file))
    except GraphDatabaseError as error:
        parser.exit(1, f"Neo4j {error.code}: {error}\n")


if __name__ == "__main__":
    main()
