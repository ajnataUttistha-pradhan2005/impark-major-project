"""Capability routing compliance metric.

Metric definition:
The orchestrator routing is compliant if:
1. The expected target capability appears in the observed execution path.
2. No disallowed capability appears in the observed execution path.

Note on Semantics:
This metric evaluates capability presence and discipline across the multi-agent
workflow. It accounts for valid multi-stage prerequisite paths (e.g., calling TEXT to
resolve botanical identity before querying GRAPH facts) while enforcing that
unrelated or contradictory specialist agents (e.g., IMAGE for purely textual questions)
are not erroneously invoked. It does not score the correctness of every internal
intermediate prompt or decision in the agent conversation.
"""

from evaluation.models import Capability, RoutingObservation


def calculate_routing_compliance(
    observed_path: list[RoutingObservation],
    target_capability: Capability,
    disallowed_capabilities: list[Capability] | None = None,
) -> tuple[bool, list[str]]:
    """Determine whether the observed agent capabilities comply with expectations.

    Args:
        observed_path: Ordered observations extracted from app_turn execution.
        target_capability: The capability necessary to fulfill the query intent.
        disallowed_capabilities: Capabilities that must not be invoked for this query.

    Returns:
        (is_compliant, formatted_observed_path)
    """
    disallowed_set = set(disallowed_capabilities or [])
    observed_capabilities = {obs.capability for obs in observed_path}

    # Format the observed path preserving order and action names
    formatted_path = [f"{obs.capability.value}:{obs.action_name}" for obs in observed_path]

    has_target = target_capability in observed_capabilities
    has_disallowed = bool(observed_capabilities & disallowed_set)

    is_compliant = has_target and not has_disallowed
    return is_compliant, formatted_path
