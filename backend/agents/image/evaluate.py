"""Disjoint reference/query comparison, explicitly not an independent CNN test set."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from backend.agents.image.ranking import rank


def evaluate(cache_path: Path, output: Path) -> dict[str, Any]:
    with np.load(cache_path, allow_pickle=False) as data:
        rows = json.loads(str(data["records"]))
        labels = data["labels"].tolist()
        vectors, probabilities = data["vectors"], data["probabilities"]
        model_id = str(data["model_id"])
    unique: dict[str, int] = {}
    conflicts = []
    for index, row in enumerate(rows):
        key = row["pixel_hash"]
        if key in unique and rows[unique[key]]["label"] != row["label"]:
            conflicts.append(key)
        unique.setdefault(key, index)
    reference = [i for h, i in unique.items() if int(h[:8], 16) % 5 != 0 and h not in conflicts]
    queries = [i for h, i in unique.items() if int(h[:8], 16) % 5 == 0 and h not in conflicts]
    if not queries or not reference:
        raise ValueError("Not enough images for reference/query evaluation")
    true = np.array([labels.index(row["label"]) for row in rows])
    metrics = {name: {"top1": 0, "top5": 0} for name in ("cnn", "retrieval", "fusion")}
    per_class = {label: {"count": 0, "cnn_correct": 0} for label in labels}
    errors = []
    started = perf_counter()
    for i in queries:
        similarities = vectors[reference] @ vectors[i]
        order = np.argsort(-similarities)[:80]
        hits = [{**rows[reference[int(j)]], "similarity": float(similarities[j])} for j in order]
        for strategy in metrics:
            scores = rank(probabilities[i], labels, hits, strategy)
            predicted = np.argsort(-scores)
            metrics[strategy]["top1"] += int(predicted[0] == true[i])
            metrics[strategy]["top5"] += int(true[i] in predicted[:5])
        per_class[rows[i]["label"]]["count"] += 1
        per_class[rows[i]["label"]]["cnn_correct"] += int(probabilities[i].argmax() == true[i])
        if probabilities[i].argmax() != true[i]:
            errors.append(
                {
                    "actual": rows[i]["label"],
                    "predicted": labels[int(probabilities[i].argmax())],
                    "path": rows[i]["path"],
                }
            )
    summary = {
        name: {metric: value / len(queries) for metric, value in values.items()}
        for name, values in metrics.items()
    }
    report = {
        "model_id": model_id,
        "images": len(rows),
        "unique_pixel_hashes": len(unique),
        "duplicate_label_conflicts": len(conflicts),
        "reference_count": len(reference),
        "query_count": len(queries),
        "metrics": summary,
        "per_class": per_class,
        "cnn_errors": errors,
        "retrieval_comparison_seconds": round(perf_counter() - started, 3),
        "limitations": [
            "Supplied model may have trained on all images; CNN accuracy is not independent",
            "Exact pixel duplicates are grouped; near-duplicate/specimen leakage is not ruled out",
            "No non-plant/other-part dataset supplied; OOD and part accuracy are unmeasured",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({"images": len(rows), "queries": len(queries), "metrics": summary}), flush=True
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evaluate(args.cache, args.output)
