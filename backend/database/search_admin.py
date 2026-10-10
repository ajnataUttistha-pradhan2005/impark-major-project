"""Explicit local/cloud administration: python -m backend.database.search_admin COMMAND."""

import argparse
import asyncio
import json

from backend.agents.text.embeddings import FastEmbedProvider
from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import load_neo4j_config
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.postgres.checkpoints import checkpoints
from backend.database.postgres.client import PostgresClient
from backend.database.postgres.migrate import migrate
from backend.database.qdrant.client import QdrantStore
from backend.database.search_config import SearchSettings
from backend.database.search_sync import populate
from backend.runtime import loop_factory


async def run(command: str) -> None:
    config = SearchSettings()
    postgres, vectors = PostgresClient(config), QdrantStore(config)
    try:
        await postgres.open()
        if command == "migrate":
            await migrate(postgres)
            async with checkpoints(config) as saver:
                await saver.setup()
            await vectors.provision()
            print("PostgreSQL migrations and Qdrant provisioning complete")
        elif command == "sync":
            async with Neo4jConnection(load_neo4j_config()) as connection:
                print(
                    json.dumps(
                        await populate(
                            Neo4jClient(connection),
                            postgres,
                            vectors,
                            FastEmbedProvider(config),
                        )
                    )
                )
        else:
            print(
                json.dumps({"postgres": await postgres.health(), "qdrant": await vectors.health()})
            )
    finally:
        await vectors.close()
        await postgres.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["migrate", "sync", "health"])
    args = parser.parse_args()
    asyncio.run(run(args.command), loop_factory=loop_factory)
