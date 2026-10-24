"""Ground-truth loading, schema validation, and turn correlation."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from evaluation.models import (
    CanonicalNodeKey,
    Capability,
    EvaluationTurn,
    GraphEntityType,
    GroundTruthTestCase,
)

try:
    import yaml  # type: ignore[import-untyped]

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


def parse_ground_truth_case(data: dict[str, Any]) -> GroundTruthTestCase:
    """Parse and normalize a single ground truth test case dictionary."""
    if not isinstance(data, dict):
        raise ValueError("Test case payload must be a dictionary")

    case_id = str(data.get("case_id", "")).strip()
    if not case_id:
        raise ValueError("Test case missing mandatory 'case_id'")

    target_cap_str = str(data.get("target_capability", "")).strip().lower()
    try:
        target_cap = Capability(target_cap_str)
    except ValueError:
        raise ValueError(f"Invalid target_capability {target_cap_str!r}") from None

    disallowed_caps: list[Capability] = []
    for cap in data.get("disallowed_capabilities", [Capability.IMAGE.value]):
        try:
            disallowed_caps.append(Capability(str(cap).strip().lower()))
        except ValueError:
            continue

    relevant_nodes: list[CanonicalNodeKey] = []
    for node in data.get("relevant_nodes", []):
        if isinstance(node, dict):
            etype_str = str(node.get("entity_type", "")).strip().lower()
            bid = str(node.get("business_id", "")).strip()
            if bid:
                try:
                    etype = GraphEntityType(etype_str)
                except ValueError:
                    etype = GraphEntityType.UNKNOWN
                relevant_nodes.append(CanonicalNodeKey(entity_type=etype, business_id=bid))

    run_id: UUID | None = None
    if data.get("run_id"):
        try:
            run_id = UUID(str(data["run_id"]))
        except ValueError:
            pass

    session_id: UUID | None = None
    if data.get("session_id"):
        try:
            session_id = UUID(str(data["session_id"]))
        except ValueError:
            pass

    query_text = data.get("query_text")
    if query_text is not None:
        query_text = str(query_text).strip()

    ground_truth_claims = data.get("ground_truth_claims")
    if ground_truth_claims is not None and not isinstance(ground_truth_claims, list):
        ground_truth_claims = None

    return GroundTruthTestCase(
        case_id=case_id,
        query_text=query_text,
        run_id=run_id,
        session_id=session_id,
        target_capability=target_cap,
        disallowed_capabilities=disallowed_caps,
        relevant_nodes=relevant_nodes,
        ground_truth_claims=ground_truth_claims,
    )


def load_ground_truth_file(file_path: Path | str) -> list[GroundTruthTestCase]:
    """Load test cases from a JSON or YAML file."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Ground-truth file not found: {path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    raw_items: list[Any]
    if suffix in {".yaml", ".yml"}:
        if not YAML_AVAILABLE:
            raise RuntimeError(
                f"Cannot load YAML ground-truth file {path}: PyYAML is not installed."
            )
        loaded = yaml.safe_load(text)
        raw_items = loaded if isinstance(loaded, list) else [loaded]
    else:
        try:
            loaded = json.loads(text)
            raw_items = loaded if isinstance(loaded, list) else [loaded]
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in ground-truth file {path}: {exc}") from None

    test_cases: list[GroundTruthTestCase] = []
    for item in raw_items:
        if isinstance(item, dict):
            test_cases.append(parse_ground_truth_case(item))

    return test_cases


class GroundTruthMatcher:
    """Correlates GroundTruthTestCases with EvaluationTurns without synthetic guesses."""

    @staticmethod
    def match(
        test_cases: list[GroundTruthTestCase],
        turns: list[EvaluationTurn],
    ) -> tuple[
        list[tuple[GroundTruthTestCase, EvaluationTurn]],  # matched
        list[GroundTruthTestCase],  # unmatched test cases
        list[EvaluationTurn],  # unmatched turns
    ]:
        """Correlate ground truth cases with turns using verified identifiers.

        Matching priority:
        1. Exact run_id match
        2. Exact session_id match (if 1:1)
        3. Normalized query text match (trimmed, casefold)
        """
        matched: list[tuple[GroundTruthTestCase, EvaluationTurn]] = []
        unmatched_cases: list[GroundTruthTestCase] = []
        remaining_turns = list(turns)

        for case in test_cases:
            match_found: EvaluationTurn | None = None

            # 1. Match by run_id
            if case.run_id is not None:
                for turn in remaining_turns:
                    if turn.run_id == case.run_id:
                        match_found = turn
                        break

            # 2. Match by session_id
            if match_found is None and case.session_id is not None:
                candidates = [t for t in remaining_turns if t.session_id == case.session_id]
                if len(candidates) == 1:
                    match_found = candidates[0]

            # 3. Match by query text
            if match_found is None and case.query_text:
                normalized_query = case.query_text.strip().casefold()
                for turn in remaining_turns:
                    if turn.user_message.strip().casefold() == normalized_query:
                        match_found = turn
                        break

            if match_found is not None:
                matched.append((case, match_found))
                remaining_turns.remove(match_found)
            else:
                unmatched_cases.append(case)

        return matched, unmatched_cases, remaining_turns
