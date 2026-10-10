"""Fixed read templates only. Labels/properties follow the supplied live schema exactly."""

from enum import StrEnum


class MedicinalQuery(StrEnum):
    PLANTS = "plants"
    PLANT = "plant"
    ALIASES = "aliases"
    BY_ALIAS = "by_alias"
    PARTS = "parts"
    COMPOUNDS = "compounds"
    USES = "uses"
    BIOACTIVITIES = "bioactivities"
    TARGETS = "targets"
    DOCUMENTS = "documents"
    PLANTS_BY_COMPOUND = "plants_by_compound"
    PLANTS_BY_USE = "plants_by_use"
    COMPOUNDS_BY_TARGET = "compounds_by_target"


TEMPLATES: dict[MedicinalQuery, str] = {
    MedicinalQuery.PLANTS: """
        MATCH (n:PlantDetails) RETURN properties(n) AS node
        ORDER BY n.plant_name, n.taxonomy_id SKIP $offset LIMIT $limit
    """,
    MedicinalQuery.PLANT: """
        MATCH (n:PlantDetails {plant_name: $plant_name})
        RETURN properties(n) AS node ORDER BY n.taxonomy_id LIMIT $limit
    """,
    MedicinalQuery.ALIASES: """
        MATCH (:PlantDetails {plant_name: $plant_name})-[:HAS_ALIAS]->(n:PlantAlias)
        RETURN DISTINCT properties(n) AS node
        ORDER BY node.language, node.normalized_alias LIMIT $limit
    """,
    MedicinalQuery.BY_ALIAS: """
        MATCH (n:PlantDetails)-[:HAS_ALIAS]->(a:PlantAlias {normalized_alias: $normalized_alias})
        WHERE $language IS NULL OR a.language = $language
        RETURN DISTINCT properties(n) AS node ORDER BY node.plant_name LIMIT $limit
    """,
    MedicinalQuery.PARTS: """
        MATCH (:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(n:PlantPart)
        RETURN DISTINCT properties(n) AS node ORDER BY node.plant_part_id LIMIT $limit
    """,
    MedicinalQuery.COMPOUNDS: """
        MATCH (:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)
              -[:CONTAINS]->(n:Phytochemicals)
        WHERE $plant_part_id IS NULL OR part.plant_part_id = $plant_part_id
        RETURN DISTINCT properties(n) AS node ORDER BY node.inchi_key LIMIT $limit
    """,
    MedicinalQuery.USES: """
        MATCH (:PlantDetails {plant_name: $plant_name})-[:HAS_PART]->(part:PlantPart)
              -[:USED_FOR]->(n:TherapeuticUse)
        WHERE $plant_part_id IS NULL OR part.plant_part_id = $plant_part_id
        RETURN DISTINCT properties(n) AS node ORDER BY node.mesh_id LIMIT $limit
    """,
    MedicinalQuery.BIOACTIVITIES: """
        MATCH (:Phytochemicals {inchi_key: $inchi_key})-[:HAS_BIOACTIVITY]->(n:Bioactivity)
        RETURN DISTINCT properties(n) AS node ORDER BY node.bioactivity_id LIMIT $limit
    """,
    MedicinalQuery.TARGETS: """
        MATCH (:Phytochemicals {inchi_key: $inchi_key})-[:HAS_BIOACTIVITY]->(:Bioactivity)
              -[:MEASURED_ON]->(n:Protein_Target)
        RETURN DISTINCT properties(n) AS node ORDER BY node.uniprot_id LIMIT $limit
    """,
    MedicinalQuery.DOCUMENTS: """
        MATCH (:Bioactivity {bioactivity_id: $bioactivity_id})-[:REPORTED_IN]->(n:Document)
        RETURN DISTINCT properties(n) AS node ORDER BY node.document_chembl_id LIMIT $limit
    """,
    MedicinalQuery.PLANTS_BY_COMPOUND: """
        MATCH (n:PlantDetails)-[:HAS_PART]->(:PlantPart)
              -[:CONTAINS]->(:Phytochemicals {inchi_key: $inchi_key})
        RETURN DISTINCT properties(n) AS node ORDER BY node.plant_name LIMIT $limit
    """,
    MedicinalQuery.PLANTS_BY_USE: """
        MATCH (n:PlantDetails)-[:HAS_PART]->(:PlantPart)
              -[:USED_FOR]->(:TherapeuticUse {mesh_id: $mesh_id})
        RETURN DISTINCT properties(n) AS node ORDER BY node.plant_name LIMIT $limit
    """,
    MedicinalQuery.COMPOUNDS_BY_TARGET: """
        MATCH (n:Phytochemicals)-[:HAS_BIOACTIVITY]->(:Bioactivity)
              -[:MEASURED_ON]->(:Protein_Target {uniprot_id: $uniprot_id})
        RETURN DISTINCT properties(n) AS node ORDER BY node.inchi_key LIMIT $limit
    """,
}
