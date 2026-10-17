import re

from backend.contracts.agents import GraphAgentOutput
from backend.contracts.evidence import Evidence
from backend.contracts.response import ResponseContext
from backend.state.models import ConversationState

_QUESTION_WORDS = {
    "about",
    "and",
    "are",
    "does",
    "explain",
    "for",
    "from",
    "have",
    "more",
    "plant",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


def rank_graph_evidence(evidence: list[Evidence], question: str, plant: str) -> list[Evidence]:
    """Prefer an explicitly named term, keeping original order for equal scores."""
    plant_words = set(re.findall(r"[a-z]{4,}", plant.casefold()))
    terms = {
        word
        for word in re.findall(r"[a-z]{4,}", question.casefold())
        if word not in _QUESTION_WORDS | plant_words
    }
    if not terms:
        return evidence

    def score(item: Evidence) -> int:
        labels = " ".join(
            str(node.get(key) or "")
            for node in item.graph_nodes
            for key in (
                "therapeutic_use",
                "phytochemical_name",
                "target_name",
                "plant_part",
                "standard_type",
            )
        ).casefold()
        label_words = set(re.findall(r"[a-z]{4,}", labels))
        return len(terms & label_words)

    return sorted(evidence, key=score, reverse=True)


def build_response_context(state: ConversationState) -> ResponseContext:
    if not state.termination.ready_for_response:
        raise ValueError("Response requires an answerable or transparent outcome")
    topic_names = {
        "GET_PLANT_DETAILS": "its recorded profile",
        "GET_PLANT_PARTS": "its documented parts",
        "GET_PLANT_PART_DETAILS": "its documented parts",
        "GET_PHYTOCHEMICALS": "its recorded compounds",
        "GET_PHYTOCHEMICAL_DETAILS": "its recorded compounds",
        "GET_THERAPEUTIC_USES": "its reported uses",
        "GET_BIOACTIVITY": "its activity measurements",
        "GET_EVIDENCE": "its activity measurements",
        "GET_PROTEIN_TARGETS": "its recorded protein targets",
        "GET_DOCUMENTS": "its linked sources",
    }
    known_topics = list(
        dict.fromkeys(
            topic_names[kind]
            for evidence in state.context.citation_history
            if evidence.modality.value == "graph"
            if (kind := evidence.provenance.reference.partition(":")[0]) in topic_names
        )
    )
    return ResponseContext(
        intent=state.goal.intent,
        user_question=state.user_message,
        answer_style=(
            "explanation"
            if re.search(
                r"\b(?:explain|elaborate|what (?:does|do|is|are) .*?mean|"
                r"tell me more|expand|unpack|walk me through|go on|why)\b",
                state.user_message.casefold(),
            )
            else "overview"
        ),
        resolved_plant=state.context.active_plant if state.belief.identity_required else None,
        text_evidence=state.evidence.text,
        image_evidence=state.evidence.image,
        graph_evidence=rank_graph_evidence(
            state.evidence.graph,
            state.user_message,
            state.context.active_plant.label if state.context.active_plant else "",
        ),
        known_topics=known_topics,
        uncertainties=[g.description for g in state.evidence.gaps]
        + [
            message
            for o in state.execution.observations
            if isinstance(o.payload, GraphAgentOutput)
            for message in o.payload.limitations
        ]
        + [c.reason for c in state.evidence.contradictions]
        + (
            [state.termination.reason]
            if state.termination.reason and state.termination.reason != "Objectives satisfied"
            else []
        ),
        outcome=state.termination.reason or "Objectives satisfied",
    ).model_copy(deep=True)
