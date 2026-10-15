"""Explicit resumable image import; activation occurs only after exact count validation."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.image.retrieval import ImageVectorStore
from backend.config.settings import Settings


def read_cache(path: Path) -> tuple[list[dict[str, Any]], list[list[float]], str, str]:
    with np.load(path, allow_pickle=False) as cache:
        rows = json.loads(str(cache["records"]))
        vectors = cache["vectors"].tolist()
        model_id = str(cache["model_id"])
    if len(rows) != len(vectors) or not rows:
        raise ValueError("Incomplete image feature cache")
    dataset_id = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return rows, vectors, model_id, dataset_id


async def build(cache: Path, manifest: Path) -> None:
    settings = Settings()
    store = ImageVectorStore(settings)
    try:
        rows, vectors, model_id, dataset_id = await asyncio.to_thread(read_cache, cache)
        await store.provision()
        for start in range(0, len(rows), 64):
            await store.upsert(
                rows[start : start + 64], vectors[start : start + 64], model_id, dataset_id
            )
        count = await store.count(model_id, dataset_id)
        if count != len(rows):
            raise ValueError("Image index count mismatch; active manifest was not changed")
        value = {
            "model_id": model_id,
            "dataset_id": dataset_id,
            "dimensions": 2048,
            "count": count,
            "collection": settings.image_collection,
        }

        def activate() -> None:
            manifest.parent.mkdir(parents=True, exist_ok=True)
            temporary = manifest.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            temporary.replace(manifest)

        await asyncio.to_thread(activate)
        print(json.dumps(value))
    finally:
        await store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(build(args.cache, args.manifest))
