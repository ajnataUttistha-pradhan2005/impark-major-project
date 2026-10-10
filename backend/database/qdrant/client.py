import math
from uuid import UUID

from qdrant_client import AsyncQdrantClient, models

from backend.agents.text.catalog import NameRecord, SearchHit
from backend.database.search_config import SearchSettings


class QdrantStore:
    def __init__(self, config: SearchSettings) -> None:
        if not config.qdrant_url:
            raise ValueError("QDRANT_URL is required")
        self.config = config
        self.client = AsyncQdrantClient(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key.get_secret_value() if config.qdrant_api_key else None,
            timeout=math.ceil(config.store_timeout_seconds),
        )

    async def close(self) -> None:
        await self.client.close()

    async def health(self) -> bool:
        await self.client.get_collections()
        return True

    async def count(self, generation: UUID) -> int:
        result = await self.client.count(
            self.config.qdrant_collection,
            exact=True,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="generation",
                        match=models.MatchValue(value=str(generation)),
                    )
                ]
            ),
        )
        return result.count

    async def provision(self) -> None:
        """Explicit provisioning only, never deletes/recreates an existing collection."""
        name = self.config.qdrant_collection
        if not await self.client.collection_exists(name):
            await self.client.create_collection(
                name,
                vectors_config=models.VectorParams(
                    size=self.config.embedding_dimensions,
                    distance=models.Distance.COSINE,
                ),
            )
        await self.validate()
        await self.client.create_payload_index(name, "generation", models.PayloadSchemaType.KEYWORD)
        await self.client.create_payload_index(name, "plant_id", models.PayloadSchemaType.KEYWORD)

    async def validate(self) -> None:
        info = await self.client.get_collection(self.config.qdrant_collection)
        vectors = info.config.params.vectors
        if not isinstance(vectors, models.VectorParams) or (
            vectors.size != self.config.embedding_dimensions
            or vectors.distance != models.Distance.COSINE
        ):
            raise ValueError("Qdrant collection vector configuration mismatch")

    def _vector(self, vector: list[float]) -> None:
        if len(vector) != self.config.embedding_dimensions or not all(map(math.isfinite, vector)):
            raise ValueError("Invalid embedding vector")

    async def upsert(
        self,
        generation: UUID,
        records: list[NameRecord],
        vectors: list[list[float]],
    ) -> None:
        from uuid import uuid5

        if len(records) != len(vectors):
            raise ValueError("Record/vector cardinality mismatch")
        points = []
        for record, vector in zip(records, vectors, strict=True):
            self._vector(vector)
            payload = record.model_dump(mode="json")
            payload.update(generation=str(generation), embedding_model=self.config.embedding_model)
            points.append(
                models.PointStruct(
                    id=str(uuid5(generation, str(record.name_id))),
                    vector=vector,
                    payload=payload,
                )
            )
        if points:
            await self.client.upsert(self.config.qdrant_collection, points, wait=True)

    async def search(
        self, generation: UUID, vector: list[float], limit: int = 20
    ) -> list[SearchHit]:
        self._vector(vector)
        if not 1 <= limit <= 100:
            raise ValueError("limit outside 1..100")
        result = await self.client.query_points(
            self.config.qdrant_collection,
            query=vector,
            limit=limit,
            with_payload=True,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="generation",
                        match=models.MatchValue(value=str(generation)),
                    )
                ]
            ),
        )
        hits = []
        for point in result.points:
            payload = point.payload or {}
            if payload.get("embedding_model") != self.config.embedding_model:
                raise ValueError("Qdrant embedding model mismatch; import a new generation")
            hits.append(
                SearchHit(
                    record=NameRecord.model_validate(payload), score=point.score, method="semantic"
                )
            )
        return hits
