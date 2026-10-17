"""Deterministic, readable response renderer; accepts response_context only."""

import re

from backend.contracts.response import FinalResponse, FinalResponseRequest
from backend.llm.verbalize import answer_facts, fact_lines, interpretation, intro, limitations


class GroundedResponseProvider:
    async def generate(self, request: FinalResponseRequest) -> FinalResponse:
        context = request.response_context
        if context.outcome == "SCOPE_REJECTED":
            return FinalResponse(
                text="Each chat supports one plant. Start a new chat to discuss another plant. "
                "Cross-plant comparisons are outside this project's current scope.",
                placeholder=False,
            )
        if context.outcome == "SAFETY_ABSTENTION":
            if re.search(
                r"\b(?:safe|safety|side effects?|toxicity|toxic|contraindications?|"
                r"drug interactions?|adverse effects?)\b",
                context.user_question.casefold(),
            ):
                plant = context.resolved_plant.label if context.resolved_plant else "this plant"
                return FinalResponse(
                    text=f"I don't have enough reliable safety information here to say "
                    f"whether {plant} is safe or what side effects it may cause. "
                    "Please ask a qualified clinician before using it for health reasons. "
                    "Educational use only; not medical advice.",
                    placeholder=False,
                )
            return FinalResponse(
                text="I cannot recommend a dose or personal treatment. "
                "Please consult a qualified clinician. "
                "Educational use only; not medical advice.",
                placeholder=False,
            )
        facts = answer_facts(context)
        if facts:
            lines = [intro(context), ""]
            lines.extend(line.rstrip("\n") for line, _ in fact_lines(facts))
            meaning = interpretation(context)
            if meaning:
                lines.extend(["", meaning])
        elif context.resolved_plant and context.outcome == "Objectives satisfied":
            lines = [
                f"Identified plant: {context.resolved_plant.label}. "
                "This chat now focuses on this plant. "
                "Ask a question to explore its recorded details."
            ]
        elif context.resolved_plant:
            plant = context.resolved_plant.label
            if context.known_topics:
                options = context.known_topics[:3]
                topics = (
                    options[0]
                    if len(options) == 1
                    else " and ".join(options)
                    if len(options) == 2
                    else ", ".join(options[:-1]) + ", and " + options[-1]
                )
                invitation = (
                    f"I do have records on {topics}. Would you like to explore one of those?"
                )
            else:
                invitation = f"Would you like me to check the recorded overview for {plant}?"
            lines = [
                f"I don't currently have enough information in the available records "
                f"to answer that about {plant}. {invitation}"
            ]
        else:
            lines = ["There is not enough supported information to answer."]
        note = limitations(context, len(facts)) if facts else ""
        if note:
            lines.extend(["", note])
        if context.intent in {"GET_THERAPEUTIC_USES", "GET_BIOACTIVITY", "GET_EVIDENCE"}:
            lines.extend(["", "For learning only; this is not medical advice."])
        return FinalResponse(
            text="\n".join(lines),
            citation_ids=[fact.citation_id for fact in facts],
            placeholder=False,
            provider="grounded",
        )
