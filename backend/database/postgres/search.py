from uuid import UUID

from backend.agents.text.catalog import NameRecord, SearchHit
from backend.agents.text.resolver import normalize
from backend.contracts.agents import ResolvedMention
from backend.database.postgres.client import PostgresClient, StoreError


class PostgresNameRepository:
    def __init__(self, client: PostgresClient) -> None:
        self.client = client

    async def generation(self) -> UUID:
        value = await self.client.scalar(
            "SELECT generation FROM search_generation WHERE status='active'"
        )
        if not isinstance(value, UUID):
            raise StoreError("CATALOG_NOT_IMPORTED")
        return value

    async def entities(self, text: str) -> list[ResolvedMention]:
        query = normalize(text)
        rows = await self.client.read(
            "SELECT kind,entity_id,label,normalized_label FROM search_entity "
            "WHERE generation=$1 AND position(' ' || normalized_label || ' ' in $2)>0 "
            "ORDER BY length(normalized_label) DESC LIMIT 20",
            await self.generation(),
            f" {query} ",
        )
        rows = [
            r
            for r in rows
            if not any(
                r["normalized_label"] != other["normalized_label"]
                and r["normalized_label"] in other["normalized_label"]
                for other in rows
            )
        ]
        return [
            ResolvedMention(
                entity_id=r["entity_id"], kind=r["kind"], label=r["label"], confidence=0.99
            )
            for r in rows
            if len(r["normalized_label"]) >= 3
        ]

    async def names(self, generation: UUID) -> list[NameRecord]:
        rows = await self.client.read(
            "SELECT n.*,p.plant_name FROM search_name n JOIN search_plant p "
            "USING(generation,plant_id) WHERE n.generation=$1 ORDER BY n.name_id LIMIT 10001",
            generation,
        )
        if len(rows) > 10000:
            raise StoreError("CATALOG_LIMIT")
        return [NameRecord.model_validate(row) for row in rows]

    async def lexical(self, generation: UUID, query: str, limit: int = 40) -> list[SearchHit]:
        if not 1 <= limit <= 100:
            raise ValueError("limit outside 1..100")
        rows = await self.client.read(
            "SELECT n.*,p.plant_name, greatest(similarity(normalized_name,$2), "
            "ts_rank(search_vector,plainto_tsquery('simple',$2))) AS score "
            "FROM search_name n JOIN search_plant p USING(generation,plant_id) "
            "WHERE n.generation=$1 AND (normalized_name % $2 OR "
            "search_vector @@ plainto_tsquery('simple',$2)) "
            "ORDER BY score DESC,n.name_id LIMIT $3",
            generation,
            query,
            limit,
        )
        return [
            SearchHit(record=NameRecord.model_validate(r), score=r["score"], method="fts_trigram")
            for r in rows
        ]

    async def prefix(self, generation: UUID, query: str, limit: int = 20) -> list[NameRecord]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = await self.client.read(
            "SELECT n.*,p.plant_name FROM search_name n JOIN search_plant p "
            "USING(generation,plant_id) WHERE n.generation=$1 AND normalized_name LIKE $2 "
            "ORDER BY length(normalized_name),normalized_name LIMIT $3",
            generation,
            escaped + "%",
            limit,
        )
        return [NameRecord.model_validate(row) for row in rows]
