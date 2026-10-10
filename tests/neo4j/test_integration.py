"""Opt-in local tests. Write tests never leave a committed test node behind.

NEO4J_RUN_INTEGRATION=1 enables reads. NEO4J_TEST_WRITES=1 additionally enables writes.
Both reject remote/Aura URIs. They read the target configuration from .env.
"""

import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from dotenv import dotenv_values

from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import load_neo4j_config
from backend.database.neo4j.diagnostics import inspect_database
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.neo4j.errors import GraphDatabaseError
from backend.database.neo4j.medicinal import MedicinalPlantRepository
from backend.database.neo4j.models import Phytochemicals

pytestmark = pytest.mark.neo4j_integration


@pytest.fixture
async def live():
    if os.getenv("NEO4J_RUN_INTEGRATION") != "1":
        pytest.skip("Set NEO4J_RUN_INTEGRATION=1 to enable local database tests")
    env_file = os.getenv("NEO4J_TEST_ENV_FILE", ".env")
    config = load_neo4j_config(env_file)
    if urlsplit(config.uri).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Integration tests require a loopback URI; refusing remote/Aura database")
    environment = os.getenv("APPLICATION_ENV", dotenv_values(env_file).get("APPLICATION_ENV"))
    if environment != "development":
        pytest.fail("Integration tests require APPLICATION_ENV=development")
    config = config.model_copy(update={"allow_writes": os.getenv("NEO4J_TEST_WRITES") == "1"})
    async with Neo4jConnection(config) as connection:
        yield Neo4jClient(connection)


async def test_live_health_and_safe_parameters(live):
    assert await live.health()
    payload = "x' MATCH (n) DETACH DELETE n //"
    assert await live.scalar("RETURN $value AS value", {"value": payload}) == payload
    assert await MedicinalPlantRepository(live).plant_details(payload) == []
    assert "Neo4j/" in (await live.server_info())["agent"]


async def test_live_metadata_and_property_models(live):
    metadata = await inspect_database(live)
    assert isinstance(metadata["indexes"], list)
    assert isinstance(metadata["constraints"], list)
    labels = {row["label"] for row in metadata["labels"]}
    assert {"PlantDetails", "PlantAlias", "Phytochemicals", "Protein_Target"} <= labels
    # Verify the documented missing-property case remains readable.
    rows = await live.read(
        "MATCH (n:Phytochemicals) WHERE n.classyfire_class IS NULL "
        "RETURN properties(n) AS node LIMIT 1"
    )
    for row in rows:
        assert Phytochemicals.model_validate(row["node"]).classyfire_class is None


async def test_live_all_medicinal_queries(live):
    repo = MedicinalPlantRepository(live)
    plants = await repo.list_plants(limit=5)
    assert plants
    # Choose connected records from the live graph, not invented scientific names/IDs.
    sample = await live.single("""
        MATCH (p:PlantDetails)-[:HAS_PART]->(part:PlantPart)-[:CONTAINS]->(c:Phytochemicals)
              -[:HAS_BIOACTIVITY]->(b:Bioactivity)-[:MEASURED_ON]->(t:Protein_Target)
        MATCH (b)-[:REPORTED_IN]->(d:Document)
        RETURN p.plant_name AS plant, part.plant_part_id AS part, c.inchi_key AS compound,
               b.bioactivity_id AS activity, t.uniprot_id AS target LIMIT 1
    """)
    assert sample is not None, "No representative connected path available for query verification"
    name = sample["plant"]
    assert await repo.plant_details(name)
    aliases = await repo.aliases(name)
    assert aliases
    assert await repo.plants_by_alias(aliases[0].normalized_alias, language=aliases[0].language)
    assert await repo.parts(name)
    assert await repo.phytochemicals(name, plant_part_id=sample["part"])
    uses = await repo.therapeutic_uses(name)
    assert uses
    assert await repo.plants_used_for(uses[0].mesh_id)
    assert await repo.bioactivities(sample["compound"])
    assert await repo.protein_targets(sample["compound"])
    assert await repo.documents(sample["activity"])
    assert await repo.plants_containing(sample["compound"])
    assert await repo.compounds_targeting(sample["target"])


async def test_live_reads_reject_writes_before_execution(live):
    name = "impark-read-guard-" + str(uuid4())
    with pytest.raises(GraphDatabaseError) as exc:
        await live.read(
            "CREATE (p:PlantDetails {plant_name: $name}) RETURN p.plant_name", {"name": name}
        )
    assert exc.value.code == "READ_ONLY"
    assert (
        await live.scalar(
            "MATCH (p:PlantDetails {plant_name: $name}) RETURN count(p)", {"name": name}
        )
        == 0
    )


async def test_live_syntax_errors_are_redacted(live):
    with pytest.raises(GraphDatabaseError) as exc:
        await live.read("INVALID private-fixture-value")
    assert "private-fixture-value" not in str(exc.value)
    assert exc.value.code == "QUERY_FAILED"


def require_writes():
    if os.getenv("NEO4J_TEST_WRITES") != "1":
        pytest.skip("Set NEO4J_TEST_WRITES=1 for rollback/atomic write checks")


async def test_live_atomic_write_without_persistent_change(live):
    require_writes()
    before = await live.scalar("MATCH (n) RETURN count(n)")
    name = "impark-atomic-check-" + str(uuid4())
    result = await live.write(
        "CREATE (p:PlantDetails {plant_name: $name}) "
        "WITH p, p.plant_name AS name DELETE p RETURN name",
        {"name": name},
    )
    assert result == [{"name": name}]
    assert await live.scalar("MATCH (n) RETURN count(n)") == before


async def test_live_transaction_rollback_and_callback(live):
    require_writes()
    name = "impark-rollback-check-" + str(uuid4())
    with pytest.raises(ValueError, match="intentional rollback"):
        async with live.transaction(write=True) as tx:
            await tx.records("CREATE (:PlantDetails {plant_name: $name})", {"name": name})
            assert (
                await tx.scalar(
                    "MATCH (p:PlantDetails {plant_name: $name}) RETURN count(p)", {"name": name}
                )
                == 1
            )
            raise ValueError("intentional rollback")
    assert (
        await live.scalar(
            "MATCH (p:PlantDetails {plant_name: $name}) RETURN count(p)", {"name": name}
        )
        == 0
    )

    async def work(tx):
        await tx.records("CREATE (:PlantDetails {plant_name: $name})", {"name": name})
        count = await tx.scalar(
            "MATCH (p:PlantDetails {plant_name: $name}) RETURN count(p)", {"name": name}
        )
        await tx.records("MATCH (p:PlantDetails {plant_name: $name}) DELETE p", {"name": name})
        return count

    assert await live.execute_write(work) == 1
    assert (
        await live.scalar(
            "MATCH (p:PlantDetails {plant_name: $name}) RETURN count(p)", {"name": name}
        )
        == 0
    )
