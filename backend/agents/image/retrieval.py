"""Dedicated image collection with immutable model/dataset filtering."""

import math
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import models

from backend.config.settings import Settings
from backend.database.qdrant.client import QdrantStore


class ImageVectorStore:
    def __init__(self, settings: Settings) -> None:
        self.connection = QdrantStore(settings)
        self.client = self.connection.client
        self.collection = settings.image_collection

    async def close(self) -> None:
        await self.connection.close()

    async def validate(self) -> None:
        info = await self.client.get_collection(self.collection)
        config = info.config.params.vectors
        if (
            not isinstance(config, models.VectorParams)
            or config.size != 2048
            or (config.distance != models.Distance.COSINE)
        ):
            raise ValueError("Image collection requires 2048-dimensional cosine vectors")

    async def provision(self) -> None:
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=2048, distance=models.Distance.COSINE),
            )
        await self.validate()
        for key in ("model_id", "dataset_id", "label"):
            await self.client.create_payload_index(
                self.collection, key, models.PayloadSchemaType.KEYWORD
            )

    @staticmethod
    def scope(model_id: str, dataset_id: str) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(key=k, match=models.MatchValue(value=v))
                for k, v in (("model_id", model_id), ("dataset_id", dataset_id))
            ]
        )

    async def count(self, model_id: str, dataset_id: str) -> int:
        return (
            await self.client.count(
                self.collection, exact=True, count_filter=self.scope(model_id, dataset_id)
            )
        ).count

    async def upsert(
        self,
        records: list[dict[str, Any]],
        vectors: list[list[float]],
        model_id: str,
        dataset_id: str,
    ) -> None:
        if len(records) != len(vectors) or len(records) > 64:
            raise ValueError("Invalid image indexing batch")
        points = []
        for row, vector in zip(records, vectors, strict=True):
            self._validate(vector)
            payload = {**row, "model_id": model_id, "dataset_id": dataset_id}
            points.append(
                models.PointStruct(
                    id=str(
                        uuid5(NAMESPACE_URL, f"impark-image:{model_id}:{dataset_id}:{row['path']}")
                    ),
                    vector=vector,
                    payload=payload,
                )
            )
        if points:
            await self.client.upsert(self.collection, points=points, wait=True)

    @staticmethod
    def _validate(vector: list[float]) -> None:
        if len(vector) != 2048 or not all(math.isfinite(v) for v in vector):
            raise ValueError("Invalid image vector")

    async def search(
        self, vector: list[float], model_id: str, dataset_id: str
    ) -> list[dict[str, Any]]:
        self._validate(vector)
        result = await self.client.query_points(
            self.collection,
            query=vector,
            limit=80,
            with_payload=True,
            query_filter=self.scope(model_id, dataset_id),
        )
        return [
            {**(p.payload or {}), "similarity": p.score, "point_id": str(p.id)}
            for p in result.points
        ]
