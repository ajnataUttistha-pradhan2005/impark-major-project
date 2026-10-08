from backend.contracts.actions import ActionDefinition, ActionName, Capability

_CAPABILITIES = {
    ActionName.RESOLVE_TEXT_ENTITY: Capability.TEXT,
    ActionName.REASSESS_ENTITY: Capability.TEXT,
    ActionName.ANALYZE_IMAGE: Capability.IMAGE,
    ActionName.RETRIEVE_GRAPH: Capability.GRAPH,
    ActionName.RETRIEVE_ADDITIONAL_GRAPH_EVIDENCE: Capability.GRAPH,
    ActionName.GENERATE_RESPONSE: Capability.RESPONSE,
}
_PRECONDITIONS = {
    ActionName.RESOLVE_TEXT_ENTITY: ("text_pending",),
    ActionName.ANALYZE_IMAGE: ("validated_image", "image_pending"),
    ActionName.RETRIEVE_GRAPH: ("resolved_entity", "pending_graph_objective"),
    ActionName.RETRIEVE_ADDITIONAL_GRAPH_EVIDENCE: ("resolved_entity", "evidence_gap"),
    ActionName.REASSESS_ENTITY: ("weakened_hypothesis", "text_available"),
    ActionName.RECONCILE_MODALITIES: ("unreconciled_conflict",),
    ActionName.UPDATE_CONTEXT: ("uncontradicted_confident_candidate",),
    ActionName.RETRY_ACTION: ("retryable_failure", "remaining_retry_budget"),
    ActionName.ASK_CLARIFICATION: (
        "unresolved_identity",
        "no_useful_capability",
    ),
    ActionName.ABSTAIN: ("no_safe_progress",),
    ActionName.GENERATE_RESPONSE: ("answerable_or_transparent_outcome",),
    ActionName.COMPLETE: ("response_generated",),
}
REGISTRY = {
    name: ActionDefinition(
        name=name,
        capability=_CAPABILITIES.get(name, Capability.CONTROL),
        prerequisites=_PRECONDITIONS[name],
        safety_requirements=("budget_available", "no_terminal_state", "typed_input"),
    )
    for name in ActionName
}
