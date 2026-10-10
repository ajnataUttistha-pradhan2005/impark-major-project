"""Domain-only read repository: this is the interface exposed to application consumers.

No assumption of uniqueness: exact matches return lists. Natural names may contain spaces.
Evidence grades are not present in the graph inventory and are never inferred here.
"""

from typing import Protocol, TypeVar

from backend.database.neo4j.client import Parameters, RecordData
from backend.database.neo4j.models import (
    Bioactivity,
    Document,
    GraphNode,
    Phytochemicals,
    PlantAlias,
    PlantDetails,
    PlantPart,
    ProteinTarget,
    TherapeuticUse,
)
from backend.database.neo4j.queries import TEMPLATES, MedicinalQuery

NodeT = TypeVar("NodeT", bound=GraphNode)


class GraphReader(Protocol):
    async def read(
        self,
        cypher: str,
        parameters: Parameters | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> list[RecordData]: ...


def bounded_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Repository limit must be an integer between 1 and 100")
    return limit


class MedicinalPlantRepository:
    def __init__(self, reader: GraphReader, timeout_seconds: float = 5) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Repository timeout must be positive and at most 30 seconds")
        self._reader = reader
        self._timeout = timeout_seconds

    async def _nodes(
        self,
        query: MedicinalQuery,
        model: type[NodeT],
        parameters: Parameters,
        limit: int,
    ) -> list[NodeT]:
        rows = await self._reader.read(
            TEMPLATES[query],
            {**parameters, "limit": bounded_limit(limit)},
            timeout_seconds=self._timeout,
        )
        return [model.model_validate(row["node"]) for row in rows]

    async def list_plants(self, *, offset: int = 0, limit: int = 20) -> list[PlantDetails]:
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100000:
            raise ValueError("Invalid offset")
        return await self._nodes(MedicinalQuery.PLANTS, PlantDetails, {"offset": offset}, limit)

    async def plant_details(self, plant_name: str, *, limit: int = 20) -> list[PlantDetails]:
        return await self._nodes(
            MedicinalQuery.PLANT, PlantDetails, {"plant_name": plant_name}, limit
        )

    async def aliases(self, plant_name: str, *, limit: int = 20) -> list[PlantAlias]:
        return await self._nodes(
            MedicinalQuery.ALIASES, PlantAlias, {"plant_name": plant_name}, limit
        )

    async def plants_by_alias(
        self,
        normalized_alias: str,
        *,
        language: str | None = None,
        limit: int = 20,
    ) -> list[PlantDetails]:
        return await self._nodes(
            MedicinalQuery.BY_ALIAS,
            PlantDetails,
            {"normalized_alias": normalized_alias, "language": language},
            limit,
        )

    async def parts(self, plant_name: str, *, limit: int = 20) -> list[PlantPart]:
        return await self._nodes(MedicinalQuery.PARTS, PlantPart, {"plant_name": plant_name}, limit)

    async def phytochemicals(
        self,
        plant_name: str,
        *,
        plant_part_id: str | None = None,
        limit: int = 20,
    ) -> list[Phytochemicals]:
        return await self._nodes(
            MedicinalQuery.COMPOUNDS,
            Phytochemicals,
            {"plant_name": plant_name, "plant_part_id": plant_part_id},
            limit,
        )

    async def therapeutic_uses(
        self,
        plant_name: str,
        *,
        plant_part_id: str | None = None,
        limit: int = 20,
    ) -> list[TherapeuticUse]:
        return await self._nodes(
            MedicinalQuery.USES,
            TherapeuticUse,
            {"plant_name": plant_name, "plant_part_id": plant_part_id},
            limit,
        )

    async def bioactivities(self, inchi_key: str, *, limit: int = 20) -> list[Bioactivity]:
        return await self._nodes(
            MedicinalQuery.BIOACTIVITIES, Bioactivity, {"inchi_key": inchi_key}, limit
        )

    async def protein_targets(self, inchi_key: str, *, limit: int = 20) -> list[ProteinTarget]:
        return await self._nodes(
            MedicinalQuery.TARGETS, ProteinTarget, {"inchi_key": inchi_key}, limit
        )

    async def documents(self, bioactivity_id: str, *, limit: int = 20) -> list[Document]:
        return await self._nodes(
            MedicinalQuery.DOCUMENTS, Document, {"bioactivity_id": bioactivity_id}, limit
        )

    async def plants_containing(self, inchi_key: str, *, limit: int = 20) -> list[PlantDetails]:
        return await self._nodes(
            MedicinalQuery.PLANTS_BY_COMPOUND, PlantDetails, {"inchi_key": inchi_key}, limit
        )

    async def plants_used_for(self, mesh_id: str, *, limit: int = 20) -> list[PlantDetails]:
        return await self._nodes(
            MedicinalQuery.PLANTS_BY_USE, PlantDetails, {"mesh_id": mesh_id}, limit
        )

    async def compounds_targeting(
        self, uniprot_id: str, *, limit: int = 20
    ) -> list[Phytochemicals]:
        return await self._nodes(
            MedicinalQuery.COMPOUNDS_BY_TARGET, Phytochemicals, {"uniprot_id": uniprot_id}, limit
        )
