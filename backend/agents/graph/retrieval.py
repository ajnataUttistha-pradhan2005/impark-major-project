"""Bounded plant-scoped retrieval; only code-owned Cypher reaches the driver."""

import json
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.agents.common.parts import PART_NAMES
from backend.contracts.agents import GraphAgentInput, GraphAgentOutput, QueryType
from backend.contracts.evidence import Contradiction, Evidence, EvidenceGap, Modality, Provenance
from backend.database.neo4j.client import Neo4jClient
from backend.database.postgres.client import PostgresClient

PATH = "(p:PlantDetails {plant_name:$name})"
PART = "-[:HAS_PART]->(part:PlantPart)"
COMPOUND = PART + "-[:CONTAINS]->(compound:Phytochemicals)"
ACTIVITY = COMPOUND + "-[:HAS_BIOACTIVITY]->(activity:Bioactivity)"
PATTERNS = {
    QueryType.GET_PLANT_DETAILS: ("", "p"),
    QueryType.GET_PLANT_PARTS: (PART, "part"),
    QueryType.GET_PLANT_PART_DETAILS: (PART, "part"),
    QueryType.GET_PHYTOCHEMICALS: (COMPOUND, "compound"),
    QueryType.GET_PHYTOCHEMICAL_DETAILS: (COMPOUND, "compound"),
    QueryType.GET_THERAPEUTIC_USES: (PART + "-[:USED_FOR]->(use:TherapeuticUse)", "use"),
    QueryType.GET_BIOACTIVITY: (ACTIVITY, "activity"),
    QueryType.GET_PROTEIN_TARGETS: (
        ACTIVITY + "-[:MEASURED_ON]->(target:Protein_Target)",
        "target",
    ),
    QueryType.GET_DOCUMENTS: (ACTIVITY + "-[:REPORTED_IN]->(document:Document)", "document"),
    QueryType.GET_EVIDENCE: (ACTIVITY, "activity"),
    QueryType.GET_PLANTS_CONTAINING_COMPOUND: (COMPOUND, "p"),
    QueryType.GET_PLANTS_FOR_THERAPEUTIC_USE: (PART + "-[:USED_FOR]->(use:TherapeuticUse)", "p"),
    QueryType.GET_COMPOUNDS_TARGETING_PROTEIN: (
        ACTIVITY + "-[:MEASURED_ON]->(target:Protein_Target)",
        "compound",
    ),
}


def _compile(pattern: str, result: str) -> str:
    filters = []
    if "(part:" in pattern:
        filters.append(
            "($part IS NULL OR part.plant_part_id=$part OR toLower(part.plant_part) IN $parts)"
        )
    for variable, field, parameter in [
        ("compound", "inchi_key", "compound"),
        ("target", "uniprot_id", "target"),
        ("activity", "bioactivity_id", "activity"),
        ("document", "document_chembl_id", "document"),
        ("use", "mesh_id", "use"),
    ]:
        if f"({variable}:" in pattern:
            filters.append(f"(${parameter} IS NULL OR {variable}.{field}=${parameter})")
    where = " WHERE " + " AND ".join(filters) if filters else ""
    return (
        "MATCH path="
        + PATH
        + pattern
        + where
        + f" RETURN DISTINCT properties({result}) AS fact, "
        + "[n IN nodes(path) | properties(n)] AS nodes, "
        + "[r IN relationships(path) | type(r)] AS relations "
        + "ORDER BY nodes, fact LIMIT $limit"
    )


QUERIES = {kind: _compile(*spec) for kind, spec in PATTERNS.items()}
QUERIES[QueryType.GET_EVIDENCE] = (
    "MATCH path="
    + PATH
    + ACTIVITY
    + " WHERE ($part IS NULL OR part.plant_part_id=$part OR toLower(part.plant_part) IN $parts)"
    + " AND ($compound IS NULL OR compound.inchi_key=$compound)"
    + " AND ($activity IS NULL OR activity.bioactivity_id=$activity)"
    + " OPTIONAL MATCH (activity)-[:REPORTED_IN]->(document:Document)"
    + " OPTIONAL MATCH (activity)-[:MEASURED_ON]->(target:Protein_Target)"
    + " WITH path, activity, document, target WHERE "
    + "($document IS NULL OR document.document_chembl_id=$document) AND "
    + "($target IS NULL OR target.uniprot_id=$target)"
    + " RETURN DISTINCT properties(activity) AS fact, "
    + "[n IN nodes(path) | properties(n)] + "
    + "CASE WHEN document IS NULL THEN [] ELSE [properties(document)] END + "
    + "CASE WHEN target IS NULL THEN [] ELSE [properties(target)] END AS nodes, "
    + "[r IN relationships(path) | type(r)] + "
    + "CASE WHEN document IS NULL THEN [] ELSE ['REPORTED_IN'] END + "
    + "CASE WHEN target IS NULL THEN [] ELSE ['MEASURED_ON'] END AS relations "
    + "ORDER BY nodes, fact LIMIT $limit"
)


class PlantGraphRetrieval:
    def __init__(self, graph: Neo4jClient, postgres: PostgresClient) -> None:
        self.graph, self.postgres = graph, postgres

    async def retrieve(self, request: GraphAgentInput) -> GraphAgentOutput:
        query = request.query
        if query.query_type == QueryType.COMPARE_PLANTS or query.parameters.comparison_plant_id:
            return self._gap(
                request, "One plant per chat; cross-plant comparisons are out of scope."
            )
        try:
            plant_uuid = UUID(str(query.parameters.plant_id))
        except ValueError:
            return self._gap(request, "Establish one application plant identity before retrieval.")
        if query.query_type == QueryType.TRACE_EVIDENCE:
            traced = next(
                (
                    e
                    for e in request.prior_evidence
                    if str(e.evidence_id) == query.parameters.evidence_id
                    and e.graph_scope.get("plant_id") == str(plant_uuid)
                ),
                None,
            )
            if traced is None:
                return self._gap(request, "Citation is unavailable in this plant's recent history.")
            return GraphAgentOutput(
                evidence=[traced.model_copy(deep=True)],
                completed_objectives=request.objective_ids,
                placeholder=False,
                limitations=[
                    "This is the previously retrieved citation snapshot, not a fresh read."
                ],
            )
        pattern = PATTERNS[query.query_type][0]
        for field, variable in [
            ("part_id", "part"),
            ("compound_id", "compound"),
            ("target_id", "target"),
            ("therapeutic_use_id", "use"),
            ("activity_id", "activity"),
            ("document_id", "document"),
        ]:
            if (
                getattr(query.parameters, field)
                and f"({variable}:" not in pattern
                and not (
                    query.query_type == QueryType.GET_EVIDENCE
                    and variable in {"target", "document"}
                )
            ):
                return self._gap(
                    request, f"The requested {field} filter is not valid for this query."
                )
        name = await self.postgres.scalar(
            "SELECT p.plant_name FROM search_plant p JOIN search_generation g USING(generation) "
            "WHERE g.status='active' AND p.plant_id=$1",
            plant_uuid,
        )
        if not isinstance(name, str):
            return self._gap(request, "Plant identity is absent from the active catalog.")
        part = query.parameters.part_id
        parts = list(PART_NAMES.get(part or "", (part,) if part else ()))
        rows = await self.graph.read(
            QUERIES[query.query_type],
            {
                "name": name,
                "part": part,
                "parts": parts,
                "limit": query.limit + 1,
                "compound": query.parameters.compound_id,
                "target": query.parameters.target_id,
                "use": query.parameters.therapeutic_use_id,
                "activity": query.parameters.activity_id,
                "document": query.parameters.document_id,
            },
            timeout_seconds=query.timeout_seconds,
        )
        if not rows:
            return self._gap(
                request, "No matching graph records; absence does not disprove a claim."
            )
        evidence: list[Evidence] = []
        limitations = []
        contradictions: list[Contradiction] = []
        seen: dict[tuple[str, str], tuple[str, UUID]] = {}
        for row in rows[: query.limit]:
            claim = json.dumps(
                row["fact"],
                ensure_ascii=False,
                sort_keys=True,
            )
            if len(claim) > 4000:
                limitations.append(
                    "A graph record exceeded the evidence size limit and was omitted."
                )
                continue
            scope = {k: str(v) for k, v in query.parameters.model_dump().items() if v is not None}
            identifier = uuid5(NAMESPACE_URL, str(plant_uuid) + json.dumps(row, sort_keys=True))
            links = []
            for index, relation in enumerate(row["relations"]):
                source = 3 if relation in {"REPORTED_IN", "MEASURED_ON"} else index
                links.append((source, relation, index + 1))
            for node in row["nodes"]:
                identity = next(
                    (
                        (key, str(node[key]))
                        for key in (
                            "plant_part_id",
                            "inchi_key",
                            "bioactivity_id",
                            "uniprot_id",
                            "document_chembl_id",
                            "mesh_id",
                            "plant_name",
                        )
                        if node.get(key)
                    ),
                    None,
                )
                if identity is None:
                    limitations.append("A path node has no documented stable identifier.")
                    continue
                serialized = json.dumps(node, sort_keys=True)
                previous = seen.get(identity)
                if previous and previous[0] != serialized and len(contradictions) < 20:
                    contradictions.append(
                        Contradiction(
                            entity_ids=[identity[1]],
                            evidence_refs=[previous[1], identifier],
                            reason=f"Conflicting properties for graph identifier {identity[0]}.",
                            affects_identity=False,
                        )
                    )
                seen[identity] = (serialized, identifier)
            urls = sorted(
                {
                    str(v)
                    for node in row["nodes"]
                    for k, v in node.items()
                    if k.endswith("url")
                    and isinstance(v, str)
                    and v.startswith(("https://", "http://"))
                }
            )[:20]
            evidence.append(
                Evidence(
                    evidence_id=identifier,
                    modality=Modality.GRAPH,
                    claim=claim,
                    confidence=1,
                    source_quality=0,
                    provenance=Provenance(
                        source_id=str(plant_uuid),
                        source_type="neo4j",
                        reference=f"{query.query_type.value}: {name}",
                    ),
                    supports=[str(plant_uuid)],
                    graph_path=row["relations"],
                    source_urls=urls,
                    graph_scope=scope,
                    graph_nodes=row["nodes"],
                    graph_links=links,
                )
            )
        truncated = len(rows) > query.limit
        if truncated:
            limitations.append(
                f"Showing at most {query.limit} evidence paths; more records exist. "
                "Narrow the part, compound or target to refine retrieval."
            )
        if query.query_type == QueryType.GET_EVIDENCE and any(
            "REPORTED_IN" not in e.graph_path for e in evidence
        ):
            limitations.append("Some bioactivity records have no linked document in this graph.")
        if query.query_type == QueryType.GET_EVIDENCE and any(
            "MEASURED_ON" not in e.graph_path for e in evidence
        ):
            limitations.append(
                "Some bioactivity records have no linked protein target in this graph."
            )
        if not evidence:
            return self._gap(
                request, "Matching records could not fit the bounded evidence envelope."
            )
        return GraphAgentOutput(
            evidence=evidence,
            completed_objectives=request.objective_ids,
            placeholder=False,
            truncated=truncated,
            limitations=list(dict.fromkeys(limitations)),
            contradictions=contradictions,
        )

    @staticmethod
    def _gap(request: GraphAgentInput, reason: str) -> GraphAgentOutput:
        return GraphAgentOutput(
            placeholder=False,
            gaps=[
                EvidenceGap(objective_id=identifier, description=reason, recoverable=False)
                for identifier in request.objective_ids
            ],
        )
