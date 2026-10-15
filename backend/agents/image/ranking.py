"""Auditable score fusion; ranking scores are not calibrated probabilities."""

from typing import Any

import numpy as np

from backend.agents.image.model import FloatArray


def retrieval_scores(labels: list[str], hits: list[dict[str, Any]]) -> FloatArray:
    support: dict[str, list[float]] = {label: [] for label in labels}
    seen = set()
    for hit in hits:
        identity = hit.get("pixel_hash", hit.get("sha256", hit.get("point_id")))
        if identity in seen or hit.get("label") not in support:
            continue
        seen.add(identity)
        support[hit["label"]].append(float(hit["similarity"]))
    weights = np.array(
        [
            sum(np.exp(12 * (v - 1)) for v in sorted(support[label], reverse=True)[:3])
            for label in labels
        ],
        dtype=np.float32,
    )
    return weights / weights.sum() if weights.sum() else weights


def rank(
    probabilities: FloatArray,
    labels: list[str],
    hits: list[dict[str, Any]],
    strategy: str,
    cnn_weight: float = 0.75,
) -> FloatArray:
    retrieved = retrieval_scores(labels, hits)
    if strategy == "cnn" or not hits:
        return probabilities.copy()
    if strategy == "retrieval":
        return retrieved
    return cnn_weight * probabilities + (1 - cnn_weight) * retrieved
