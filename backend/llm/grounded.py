"""Deterministic response renderer for the demo; accepts response_context only."""

import json

from backend.contracts.response import FinalResponse, FinalResponseRequest


class GroundedResponseProvider:
    async def generate(self, request: FinalResponseRequest) -> FinalResponse:
        context = request.response_context
        lines = []
        if context.outcome == "SCOPE_REJECTED":
            return FinalResponse(
                text="Each chat supports one plant. Start a new chat to discuss another plant. "
                "Cross-plant comparisons are outside this project's current scope.",
                placeholder=False,
            )
        if context.outcome == "SAFETY_ABSTENTION":
            lines.append(
                "I cannot recommend a dose or personal treatment. Consult a qualified clinician."
            )
        elif context.resolved_plant and context.outcome == "Objectives satisfied":
            lines.append(f"Identified plant: {context.resolved_plant.label}.")
        elif context.resolved_plant:
            lines.append(f"Current plant context: {context.resolved_plant.label}.")
        citations = []
        for evidence in context.graph_evidence:
            try:
                fact = json.loads(evidence.claim)
            except (ValueError, TypeError):
                fact = None
            if isinstance(fact, dict):
                summary = "; ".join(
                    f"{key.replace('_', ' ')}: {value}"
                    for key, value in fact.items()
                    if value is not None
                )
            else:
                summary = evidence.claim
            lines.append(
                f"{evidence.provenance.reference}: {summary} [evidence: {evidence.evidence_id}; "
                f"class: {evidence.evidence_type.value}]"
            )
            citations.append(evidence.evidence_id)
            if context.intent == "TRACE_EVIDENCE":
                for source, relationship, target in evidence.graph_links:
                    nodes = evidence.graph_nodes
                    if source < len(nodes) and target < len(nodes):
                        lines.append(
                            f"Source path: {nodes[source]} —{relationship}→ {nodes[target]}"
                        )
            if evidence.source_urls:
                lines.append("Recorded sources: " + ", ".join(evidence.source_urls))
        if context.uncertainties:
            lines.append("Limitations: " + "; ".join(context.uncertainties))
        if not lines:
            lines.append("There is not enough supported information to answer.")
        lines.append(
            "Educational use only; not medical advice. "
            "Reported uses do not establish clinical efficacy."
        )
        return FinalResponse(text="\n".join(lines), citation_ids=citations, placeholder=False)
