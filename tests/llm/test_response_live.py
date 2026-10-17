"""Explicit opt-in graph-to-Ollama response check against local development stores."""

import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from backend.agents.graph.retrieval import PlantGraphRetrieval
from backend.config.settings import Settings
from backend.contracts.actions import Action, ActionName, AgentInvocation, Capability
from backend.contracts.agents import (
    CandidatePlant,
    GraphAgentInput,
    GraphParameters,
    GraphQuery,
    QueryType,
)
from backend.contracts.base import CorrelationMetadata
from backend.contracts.response import FinalResponseRequest, ResponseContext
from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.config import load_neo4j_config
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.postgres.client import PostgresClient
from backend.llm.guarded import GuardedResponseProvider
from backend.llm.ollama import OllamaModel

pytestmark = pytest.mark.skipif(os.getenv("RESPONSE_RUN_INTEGRATION") != "1", reason="Local opt-in")


@pytest.mark.parametrize(
    "kind",
    [
        QueryType.GET_PLANT_DETAILS,
        QueryType.GET_PHYTOCHEMICALS,
        QueryType.GET_THERAPEUTIC_USES,
        QueryType.GET_BIOACTIVITY,
        QueryType.GET_PROTEIN_TARGETS,
        QueryType.GET_DOCUMENTS,
    ],
)
async def test_real_graph_records_render_as_supported_answers(kind: QueryType) -> None:
    settings = Settings()
    graph_config = load_neo4j_config()
    assert urlsplit(graph_config.uri).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(settings.database_url.get_secret_value()).hostname in {"localhost", "127.0.0.1"}
    assert urlsplit(settings.ollama_base_url or "").hostname in {"localhost", "127.0.0.1"}
    postgres = PostgresClient(settings)
    await postgres.open()
    model = OllamaModel(settings)
    try:
        assert await model.health()
        async with Neo4jConnection(graph_config) as connection:
            graph = Neo4jClient(connection)
            sample = await graph.single(
                "MATCH (p:PlantDetails)-[:HAS_PART]->(:PlantPart)-[:CONTAINS]->"
                "(:Phytochemicals)-[:HAS_BIOACTIVITY]->(a:Bioactivity) "
                "MATCH (a)-[:REPORTED_IN]->(:Document) "
                "MATCH (a)-[:MEASURED_ON]->(:Protein_Target) "
                "RETURN p.plant_name AS name ORDER BY name LIMIT 1"
            )
            assert sample is not None
            name = sample["name"]
            plant_id = await postgres.scalar(
                "SELECT p.plant_id FROM search_plant p "
                "JOIN search_generation g USING(generation) "
                "WHERE g.status='active' AND p.plant_name=$1",
                name,
            )
            assert plant_id is not None
            request = GraphAgentInput(
                invocation=AgentInvocation(
                    correlation=CorrelationMetadata(session_id=uuid4()),
                    action=Action(name=ActionName.RETRIEVE_GRAPH),
                    capability=Capability.GRAPH,
                ),
                query=GraphQuery(
                    query_type=kind,
                    parameters=GraphParameters(plant_id=str(plant_id)),
                    limit=4,
                ),
                objective_ids=[uuid4()],
            )
            result = await PlantGraphRetrieval(graph, postgres).retrieve(request)
            assert result.evidence
            context = ResponseContext(
                intent=kind.value,
                user_question={
                    QueryType.GET_PLANT_DETAILS: "Tell me about this plant",
                    QueryType.GET_PHYTOCHEMICALS: "What compounds are in it?",
                    QueryType.GET_THERAPEUTIC_USES: "What are its uses?",
                    QueryType.GET_BIOACTIVITY: "Explain its bioactivity measurements",
                    QueryType.GET_PROTEIN_TARGETS: "What protein targets are recorded?",
                    QueryType.GET_DOCUMENTS: "What sources are linked?",
                }[kind],
                resolved_plant=CandidatePlant(plant_id=str(plant_id), label=name, confidence=1),
                graph_evidence=result.evidence,
                outcome="Objectives satisfied",
            )
            response = await GuardedResponseProvider(model).generate(
                FinalResponseRequest(response_context=context)
            )
            if os.getenv("RESPONSE_CAPTURE_OUTPUT") == "1":
                print(
                    f"\n{kind.value}: provider={response.provider} "
                    f"fallback={response.fallback_used}\n{response.text}"
                )
            assert response.provider in {"ollama", "grounded"}
            assert response.citation_ids
            assert set(response.citation_ids) <= {e.evidence_id for e in result.evidence}
            assert name in response.text
            assert "GET_" not in response.text
            assert "source_url" not in response.text
            assert "graph_path" not in response.text
            assert "guardrail" not in response.text.casefold()
            if kind == QueryType.GET_THERAPEUTIC_USES:
                assert "cure" not in response.text.casefold()
    finally:
        await model.close()
        await postgres.close()
