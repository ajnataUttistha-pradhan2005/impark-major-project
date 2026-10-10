"""Property projections from the supplied 2026-10-09 inventory, not inferred constraints.

All properties are optional: an inventory's NOT NULL string is not a schema guarantee.
In particular, classyfire_class is missing on one node in the supplied snapshot.
"""

from pydantic import BaseModel, ConfigDict


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class PlantDetails(GraphNode):
    plant_name: str | None = None
    source: str | None = None
    regional_status: str | None = None
    iucn_url: str | None = None
    common_names: str | None = None
    iucn_year: str | None = None
    taxonomy_id: str | None = None
    global_status: str | None = None
    biodiversity_url: str | None = None


class PlantAlias(GraphNode):
    normalized_alias: str | None = None
    language: str | None = None
    alias_type: str | None = None
    alias: str | None = None
    plant_name: str | None = None


class PlantPart(GraphNode):
    plant_part_id: str | None = None
    plant_name: str | None = None
    source_url: str | None = None
    source: str | None = None
    plant_part: str | None = None


class Phytochemicals(GraphNode):
    classyfire_kingdom: str | None = None
    classyfire_superclass: str | None = None
    inchi_key: str | None = None
    classyfire_class: str | None = None
    smiles: str | None = None
    phytochemical_name: str | None = None
    classyfire_subclass: str | None = None
    imppat_id: str | None = None
    source_url: str | None = None
    chembl_id: str | None = None
    source: str | None = None


class TherapeuticUse(GraphNode):
    mesh_id: str | None = None
    mesh_sub_category_name: str | None = None
    source_url: str | None = None
    mesh_category_name: str | None = None
    mesh_category: str | None = None
    source: str | None = None
    therapeutic_use: str | None = None


class ProteinTarget(GraphNode):
    uniprot_id: str | None = None
    source: str | None = None
    uniprot_url: str | None = None
    target_chembl_id: str | None = None
    target_type: str | None = None
    target_name: str | None = None
    target_organism: str | None = None
    chembl_url: str | None = None


class Bioactivity(GraphNode):
    source_url: str | None = None
    standard_value: float | None = None
    source: str | None = None
    standard_relation: str | None = None
    high_confidence_tier: str | None = None
    bioactivity_id: str | None = None
    normalized_value_nm: float | None = None
    standard_units: str | None = None
    standard_type: str | None = None


class Document(GraphNode):
    document_chembl_id: str | None = None
    source_id: int | None = None
    document_journal: str | None = None
    source_url: str | None = None
    source: str | None = None
    document_year: str | None = None
