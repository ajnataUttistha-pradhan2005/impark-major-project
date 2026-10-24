"""Extraction and canonical normalization of persisted turn states."""

from datetime import datetime
from typing import Any
from uuid import UUID

from evaluation.models import (
    CanonicalNodeKey,
    Capability,
    EvaluationTurn,
    GeneratedResponse,
    GraphEntityType,
    MetricDiagnostic,
    RoutingObservation,
)


def extract_canonical_node(
    node: dict[str, Any],
) -> tuple[CanonicalNodeKey | None, MetricDiagnostic | None]:
    """Normalize a raw Neo4j node property dictionary into a canonical business key."""
    if not isinstance(node, dict) or not node:
        return None, MetricDiagnostic(
            code="EMPTY_NODE",
            message="Encountered empty or non-dictionary node in graph evidence.",
            details={"raw": str(node)},
        )

    # 1. Primary business identifiers
    if "inchi_key" in node and node["inchi_key"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.COMPOUND,
                business_id=str(node["inchi_key"]).strip(),
            ),
            None,
        )

    if "uniprot_id" in node and node["uniprot_id"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.PROTEIN_TARGET,
                business_id=str(node["uniprot_id"]).strip(),
            ),
            None,
        )

    if "plant_part_id" in node and node["plant_part_id"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.PLANT_PART,
                business_id=str(node["plant_part_id"]).strip(),
            ),
            None,
        )

    if "bioactivity_id" in node and node["bioactivity_id"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.BIOACTIVITY,
                business_id=str(node["bioactivity_id"]).strip(),
            ),
            None,
        )

    if "document_chembl_id" in node and node["document_chembl_id"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.DOCUMENT,
                business_id=str(node["document_chembl_id"]).strip(),
            ),
            None,
        )

    if "mesh_id" in node and node["mesh_id"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.THERAPEUTIC_USE,
                business_id=str(node["mesh_id"]).strip(),
            ),
            None,
        )

    if "plant_name" in node and node["plant_name"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.PLANT,
                business_id=str(node["plant_name"]).strip(),
            ),
            None,
        )

    if "plant_id" in node and node["plant_id"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.PLANT,
                business_id=str(node["plant_id"]).strip(),
            ),
            None,
        )

    if "normalized_alias" in node and node["normalized_alias"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.PLANT_ALIAS,
                business_id=str(node["normalized_alias"]).strip().casefold(),
            ),
            None,
        )

    # 2. Secondary fallback entity attributes supported in test fixtures & catalogs
    if "phytochemical_name" in node and node["phytochemical_name"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.COMPOUND,
                business_id=str(node["phytochemical_name"]).strip(),
            ),
            None,
        )

    if "compound_name" in node and node["compound_name"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.COMPOUND,
                business_id=str(node["compound_name"]).strip(),
            ),
            None,
        )

    if "plant_part" in node and node["plant_part"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.PLANT_PART,
                business_id=str(node["plant_part"]).strip(),
            ),
            None,
        )

    if "target_name" in node and node["target_name"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.PROTEIN_TARGET,
                business_id=str(node["target_name"]).strip(),
            ),
            None,
        )

    if "therapeutic_use" in node and node["therapeutic_use"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.THERAPEUTIC_USE,
                business_id=str(node["therapeutic_use"]).strip(),
            ),
            None,
        )

    if "alias" in node and node["alias"]:
        return (
            CanonicalNodeKey(
                entity_type=GraphEntityType.PLANT_ALIAS,
                business_id=str(node["alias"]).strip().casefold(),
            ),
            None,
        )

    return None, MetricDiagnostic(
        code="UNRECOGNIZED_NODE",
        message="Graph node missing recognized business key or entity property.",
        details={"keys": sorted(node.keys())},
    )


def extract_routing_observations(
    observations_raw: list[dict[str, Any]],
) -> list[RoutingObservation]:
    """Extract ordered execution path from execution observations."""
    routing_path: list[RoutingObservation] = []
    if not isinstance(observations_raw, list):
        return routing_path

    for idx, obs in enumerate(observations_raw):
        if not isinstance(obs, dict):
            continue

        raw_component = str(obs.get("component", "")).strip().lower()
        try:
            capability = Capability(raw_component)
        except ValueError:
            # Fallback check on invocation capability
            inv = obs.get("invocation")
            if isinstance(inv, dict) and "capability" in inv:
                try:
                    capability = Capability(str(inv["capability"]).strip().lower())
                except ValueError:
                    continue
            else:
                continue

        action_name = "unknown"
        inv = obs.get("invocation")
        if isinstance(inv, dict):
            act = inv.get("action")
            if isinstance(act, dict) and "name" in act:
                action_name = str(act["name"])
            elif "action_name" in inv:
                action_name = str(inv["action_name"])

        routing_path.append(
            RoutingObservation(
                step_index=idx,
                capability=capability,
                action_name=action_name,
                component_raw=raw_component,
            )
        )
    return routing_path


def extract_evaluation_turn(
    run_id: UUID,
    session_id: UUID,
    state: dict[str, Any],
    created_at: datetime | None = None,
) -> EvaluationTurn:
    """Transform raw ConversationState dictionary into normalized EvaluationTurn."""
    diagnostics: list[MetricDiagnostic] = []

    if not isinstance(state, dict):
        return EvaluationTurn(
            run_id=run_id,
            session_id=session_id,
            user_message="",
            status="INVALID_STATE",
            created_at=created_at,
            diagnostics=[
                MetricDiagnostic(
                    code="CORRUPT_STATE_PAYLOAD",
                    message="State is not a valid JSON dictionary.",
                )
            ],
        )

    user_message = str(state.get("user_message", "")).strip()
    status = "UNKNOWN"
    termination = state.get("termination")
    if isinstance(termination, dict) and "status" in termination:
        status = str(termination["status"])

    # 1. Routing observations
    exec_state = state.get("execution")
    raw_observations = exec_state.get("observations", []) if isinstance(exec_state, dict) else []
    routing_path = extract_routing_observations(raw_observations)

    # 2. Graph node extraction & deduplication
    evidence_state = state.get("evidence")
    graph_evidence = evidence_state.get("graph", []) if isinstance(evidence_state, dict) else []

    seen_keys: set[CanonicalNodeKey] = set()
    canonical_nodes: list[CanonicalNodeKey] = []
    unrecognized_nodes: list[dict[str, Any]] = []
    missing_key_nodes: list[dict[str, Any]] = []

    if isinstance(graph_evidence, list):
        for ev in graph_evidence:
            if not isinstance(ev, dict):
                continue
            nodes = ev.get("graph_nodes", [])
            if not isinstance(nodes, list):
                continue
            for node_dict in nodes:
                key, diag = extract_canonical_node(node_dict)
                if key is not None:
                    if key not in seen_keys:
                        seen_keys.add(key)
                        canonical_nodes.append(key)
                else:
                    if diag and diag.code == "EMPTY_NODE":
                        missing_key_nodes.append(node_dict)
                    else:
                        unrecognized_nodes.append(node_dict)
                    if diag:
                        diagnostics.append(diag)

    # 3. Response extraction
    response_obj: GeneratedResponse | None = None
    resp_raw = state.get("response")
    if isinstance(resp_raw, dict):
        citation_ids: list[UUID] = []
        for cid in resp_raw.get("citation_ids", []):
            try:
                citation_ids.append(UUID(str(cid)))
            except (ValueError, TypeError):
                continue

        response_obj = GeneratedResponse(
            text=str(resp_raw.get("text", "")),
            citation_ids=citation_ids,
            provider=str(resp_raw.get("provider", "")),
            model=resp_raw.get("model"),
            claims_available=False,
            claims=[],
        )

    return EvaluationTurn(
        run_id=run_id,
        session_id=session_id,
        user_message=user_message,
        status=status,
        created_at=created_at,
        execution_path=routing_path,
        retrieved_graph_nodes=canonical_nodes,
        unrecognized_graph_nodes=unrecognized_nodes,
        missing_key_nodes=missing_key_nodes,
        response=response_obj,
        raw_state=state,
        diagnostics=diagnostics,
    )
