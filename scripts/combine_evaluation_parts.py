"""Utility to combine and verify partitioned evaluation JSONL datasets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def combine_parts(
    part1_path: Path,
    part2_path: Path,
    output_path: Path,
) -> int:
    """Combine two evaluation JSONL files into a single consolidated file."""
    if not part1_path.exists():
        raise FileNotFoundError(f"Part 1 file not found: {part1_path}")
    if not part2_path.exists():
        raise FileNotFoundError(f"Part 2 file not found: {part2_path}")

    records: list[dict] = []
    seen_cases: set[tuple[str, str]] = set()

    for part_idx, path in enumerate([part1_path, part2_path], 1):
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception as e:
                    raise ValueError(f"Invalid JSON at {path}:{line_no}: {e}")

                p = str(obj.get("plant_name", "")).strip()
                q = str(obj.get("question", "")).strip()
                case_key = (p, q)

                if case_key in seen_cases:
                    print(f"Warning: Duplicate case detected in Part {part_idx}: {case_key}")
                seen_cases.add(case_key)
                records.append(obj)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("\n" + "=" * 65)
    print("COMBINED EVALUATION DATASETS")
    print("=" * 65)
    print(f"Part 1 source:         {part1_path}")
    print(f"Part 2 source:         {part2_path}")
    print(f"Combined destination:  {output_path}")
    print(f"Total records written: {len(records)}")
    print(f"Unique test cases:     {len(seen_cases)}")
    print("=" * 65 + "\n")

    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine evaluation_part1.jsonl and evaluation_part2.jsonl into a unified dataset."
    )
    parser.add_argument(
        "--part1",
        type=Path,
        default=Path("data/evaluation_part1.jsonl"),
        help="Path to Part 1 evaluation JSONL file",
    )
    parser.add_argument(
        "--part2",
        type=Path,
        default=Path("data/evaluation_part2.jsonl"),
        help="Path to Part 2 evaluation JSONL file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("data/all_plants_evaluation.jsonl"),
        help="Path to consolidated output JSONL file",
    )

    args = parser.parse_args()
    combine_parts(args.part1, args.part2, args.output)


if __name__ == "__main__":
    main()
