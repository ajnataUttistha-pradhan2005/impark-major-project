"""Explicit migration command only; never invoked by web startup."""

from pathlib import Path

from backend.database.postgres.client import PostgresClient


async def migrate(client: PostgresClient) -> None:
    async with client.transaction(write=True) as tx:
        await tx.execute("SELECT pg_advisory_xact_lock(72421001)")
        await tx.execute(
            "CREATE TABLE IF NOT EXISTS schema_migration "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
            if not await tx.fetchval("SELECT 1 FROM schema_migration WHERE version=$1", path.name):
                await tx.execute(path.read_text(encoding="utf-8"))
                await tx.execute("INSERT INTO schema_migration(version) VALUES($1)", path.name)
