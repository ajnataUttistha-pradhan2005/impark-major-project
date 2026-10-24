"""Tests for capability routing compliance metric."""

from evaluation.metrics.routing import calculate_routing_compliance
from evaluation.models import Capability, RoutingObservation


def test_text_to_graph_prerequisite_sequence_is_compliant():
    """Verify that multi-step TEXT -> GRAPH prerequisite sequence is compliant for GRAPH target."""
    observed = [
        RoutingObservation(
            step_index=0,
            capability=Capability.TEXT,
            action_name="resolve_plant_names",
        ),
        RoutingObservation(
            step_index=1,
            capability=Capability.GRAPH,
            action_name="retrieve_plant_graph",
        ),
    ]

    compliant, formatted = calculate_routing_compliance(
        observed_path=observed,
        target_capability=Capability.GRAPH,
        disallowed_capabilities=[Capability.IMAGE],
    )

    assert compliant is True
    assert formatted == ["text:resolve_plant_names", "graph:retrieve_plant_graph"]


def test_disallowed_image_invocation_fails_compliance():
    """Verify that invoking a disallowed capability (e.g. IMAGE on text query) causes failure."""
    observed = [
        RoutingObservation(
            step_index=0,
            capability=Capability.TEXT,
            action_name="resolve_plant_names",
        ),
        RoutingObservation(
            step_index=1,
            capability=Capability.IMAGE,
            action_name="inspect_uploaded_image",
        ),
        RoutingObservation(
            step_index=2,
            capability=Capability.GRAPH,
            action_name="retrieve_plant_graph",
        ),
    ]

    compliant, formatted = calculate_routing_compliance(
        observed_path=observed,
        target_capability=Capability.GRAPH,
        disallowed_capabilities=[Capability.IMAGE],
    )

    assert compliant is False
    assert "image:inspect_uploaded_image" in formatted


def test_missing_target_capability_fails_compliance():
    """Verify that failing to invoke the target capability results in non-compliance."""
    observed = [
        RoutingObservation(
            step_index=0,
            capability=Capability.TEXT,
            action_name="resolve_plant_names",
        )
    ]

    compliant, formatted = calculate_routing_compliance(
        observed_path=observed,
        target_capability=Capability.GRAPH,
        disallowed_capabilities=[Capability.IMAGE],
    )

    assert compliant is False
    assert formatted == ["text:resolve_plant_names"]
