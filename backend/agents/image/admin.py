"""Explicit offline image feature extraction. Never run at web startup."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from backend.agents.image.model import XceptionModel


def extract(root: Path, output: Path, model: XceptionModel) -> None:
    model.load()
    files = sorted(root.rglob("*.jpg"))
    rows, probabilities, vectors = [], [], []
    completed: dict[str, int] = {}
    if output.exists():
        with np.load(output, allow_pickle=False) as cache:
            if str(cache["model_id"]) != model.model_id:
                raise ValueError("Cache model differs; choose a new output file")
            rows = json.loads(str(cache["records"]))
            probabilities = list(cache["probabilities"])
            vectors = list(cache["vectors"])
            completed = {r["path"]: i for i, r in enumerate(rows)}
    started = perf_counter()
    for offset in range(0, len(files), 8):
        pending = []
        for path in files[offset : offset + 8]:
            content = path.read_bytes()
            record = {
                "path": path.relative_to(root).as_posix(),
                "label": path.parent.name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "pixel_hash": hashlib.sha256(model.pixels(content).tobytes()).hexdigest(),
            }
            if record["label"] not in model.labels:
                raise ValueError("Dataset label is absent from output mapping")
            if record["path"] in completed:
                if rows[completed[record["path"]]] != record:
                    raise ValueError("Dataset changed; choose a new feature cache")
                continue
            pending.append((record, content))
        if pending:
            scores, features = model.batch([p[1] for p in pending])
            rows.extend(p[0] for p in pending)
            probabilities.extend(scores)
            vectors.extend(features)
        if offset % 64 == 0 or offset + 8 >= len(files):
            output.parent.mkdir(parents=True, exist_ok=True)
            temp = output.with_suffix(".tmp.npz")
            np.savez_compressed(
                temp,
                model_id=model.model_id,
                labels=np.array(model.labels),
                records=json.dumps(rows),
                probabilities=np.array(probabilities),
                vectors=np.array(vectors),
            )
            temp.replace(output)
            print(
                json.dumps(
                    {
                        "images": len(rows),
                        "total": len(files),
                        "elapsed_seconds": round(perf_counter() - started, 1),
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["extract"])
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--classes", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    extract(args.dataset, args.output, XceptionModel(args.model, args.classes))
