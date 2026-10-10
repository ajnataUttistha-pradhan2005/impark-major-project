"""Opt-in, read-only graph checks against local Docker plus the populated name catalog."""

import os
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from test_retrieval import request

from backend.agents.graph.retrieval import QUERIES, PlantGraphRetrieval
from backend.contracts.agents import QueryType
from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import load_neo4j_config
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.postgres.client import PostgresClient
from backend.database.search_config import SearchSettings

pytestmark = pytest.mark.skipif(os.getenv("GRAPH_RUN_INTEGRATION") != "1", reason="Local opt-in")


@pytest_asyncio.fixture
async def live():
    neo = load_neo4j_config()
    settings = SearchSettings()
    assert urlsplit(neo.uri).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(settings.database_url.get_secret_value()).hostname in {"localhost", "127.0.0.1"}
    pg = PostgresClient(settings)
    await pg.open()
    try:
        async with Neo4jConnection(neo) as connection:
            client = Neo4jClient(connection)
            sample = await client.single(
                "MATCH (p:PlantDetails)-[:HAS_PART]->(part:PlantPart)-[:CONTAINS]->"
                "(c:Phytochemicals)-[:HAS_BIOACTIVITY]->(a:Bioactivity)"
                "-[:REPORTED_IN]->(d:Document) "
                "MATCH (a)-[:MEASURED_ON]->(t:Protein_Target) "
                "RETURN p.plant_name AS name, part.plant_part_id AS part, c.inchi_key AS compound, "
                "a.bioactivity_id AS activity, d.document_chembl_id AS document, "
                "t.uniprot_id AS target "
                "ORDER BY name LIMIT 1"
            )
            sample["plant"] = str(
                await pg.scalar(
                    "SELECT plant_id FROM search_plant p "
                    "JOIN search_generation g USING(generation) "
                    "WHERE g.status='active' AND plant_name=$1",
                    sample["name"],
                )
            )
            use = await client.single(
                "MATCH (p:PlantDetails {plant_name:$name})-[:HAS_PART]->(:PlantPart)"
                "-[:USED_FOR]->(u:TherapeuticUse) RETURN u.mesh_id AS id LIMIT 1",
                {"name": sample["name"]},
            )
            sample["use"] = use["id"]
            yield PlantGraphRetrieval(client, pg), sample
    finally:
        await pg.close()


@pytest.mark.parametrize("kind", list(QUERIES))
async def test_every_query_against_actual_schema(live, kind):
    repo, sample = live
    parameters = {"plant_id": sample["plant"]}
    fields = {
        QueryType.GET_PLANT_PART_DETAILS: ("part_id", "part"),
        QueryType.GET_PHYTOCHEMICAL_DETAILS: ("compound_id", "compound"),
        QueryType.GET_PLANTS_CONTAINING_COMPOUND: ("compound_id", "compound"),
        QueryType.GET_COMPOUNDS_TARGETING_PROTEIN: ("target_id", "target"),
        QueryType.GET_PLANTS_FOR_THERAPEUTIC_USE: ("therapeutic_use_id", "use"),
    }
    if kind in fields:
        field, key = fields[kind]
        parameters[field] = sample[key]
    result = await repo.retrieve(request(kind, **parameters))
    assert result.evidence, result.model_dump_json()
    assert all(e.graph_scope["plant_id"] == sample["plant"] for e in result.evidence)
    assert all(e.graph_nodes[0]["plant_name"] == sample["name"] for e in result.evidence)
    assert all(e.evidence_type == "unknown" for e in result.evidence)


async def test_source_trace_filters_and_readonly_counts(live):
    repo, sample = live
    counts = await repo.graph.read("MATCH (n) RETURN count(n) AS count")
    req = request(
        QueryType.GET_EVIDENCE,
        plant_id=sample["plant"],
        compound_id=sample["compound"],
        activity_id=sample["activity"],
        document_id=sample["document"],
        target_id=sample["target"],
    )
    result = await repo.retrieve(req)
    assert result.evidence
    evidence = result.evidence[0]
    assert "REPORTED_IN" in evidence.graph_path and "MEASURED_ON" in evidence.graph_path
    trace = request(
        QueryType.TRACE_EVIDENCE, plant_id=sample["plant"], evidence_id=str(evidence.evidence_id)
    )
    trace.prior_evidence = [evidence]
    assert (await repo.retrieve(trace)).evidence[0] == evidence
    assert await repo.graph.read("MATCH (n) RETURN count(n) AS count") == counts
    with pytest.raises(ValueError):
        req.query.parameters.compound_id = "' MATCH (n) DETACH DELETE n //"
    req.query.parameters.compound_id = "fixture:absent"
    assert (await repo.retrieve(req)).gaps
    assert await repo.graph.read("MATCH (n) RETURN count(n) AS count") == counts
