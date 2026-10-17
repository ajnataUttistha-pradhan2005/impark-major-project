"""Model-written explanations with a deterministic evidence and citation boundary.

Only a complete, validated answer reaches the stream. The fallback remains available
when the model is unavailable or cannot keep its claims inside the evidence packet.
"""

from collections.abc import AsyncIterator
from time import monotonic
from uuid import UUID

import httpx

from backend.contracts.response import (
    FinalResponse,
    FinalResponseRequest,
    ResponseChunk,
    ResponseContext,
)
from backend.llm.concise import concise_answer
from backend.llm.grounded import GroundedResponseProvider
from backend.llm.knowledge_explanation import explanation_packet, validate_explanations
from backend.llm.narrative import packet, reference_facts, validate_narrative
from backend.llm.ollama import TokenModel
from backend.llm.verbalize import answer_facts


class GuardedResponseProvider:
    def __init__(self, model: TokenModel | None = None) -> None:
        self.model = model
        self._consecutive_rejections = 0
        self._retry_after = 0.0

    async def generate(self, request: FinalResponseRequest) -> FinalResponse:
        chunks = [chunk async for chunk in self.stream(request)]
        return FinalResponse(
            text="".join(c.text for c in chunks),
            citation_ids=list(dict.fromkeys(i for c in chunks for i in c.citation_ids)),
            placeholder=False,
            provider=chunks[-1].provider if chunks else "grounded",
            model=chunks[-1].model if chunks else None,
            fallback_used=any(c.fallback_used for c in chunks),
        )

    async def stream(self, request: FinalResponseRequest) -> AsyncIterator[ResponseChunk]:
        context = request.response_context
        if context.outcome in {"SAFETY_ABSTENTION", "SCOPE_REJECTED"} or not context.graph_evidence:
            safe_request = FinalResponseRequest(
                response_context=context.model_copy(update={"graph_evidence": []})
            )
            response = await GroundedResponseProvider().generate(safe_request)
            for chunk in self._chunks(response.text, []):
                yield chunk.model_copy(update={"provider": "grounded", "model": None})
            return

        facts = answer_facts(context)
        explanatory = facts + reference_facts(context, facts)
        if (
            self.model and facts and context.answer_style == "explanation"
            and monotonic() >= self._retry_after
        ):
            try:
                prompt, schema = explanation_packet(context, facts)
                buffer = ""
                async for token in self.model.tokens(prompt, schema):
                    buffer += token
                    if len(buffer) > 16000:
                        raise ValueError("Response exceeded model output limit")
                background_notes = validate_explanations(buffer, context, facts)
                if not background_notes:
                    raise ValueError("No confident explanations")
                self._consecutive_rejections = 0
                self._retry_after = 0.0
                by_index = {note.fact_index: note.text for note in background_notes}
                for chunk in self._chunks(
                    "Here is what each record says, with a plain-language note. "
                    "The notes are general model knowledge, not additional findings "
                    "about this plant.\n\n",
                    [],
                ):
                    yield chunk
                for index, fact in enumerate(facts):
                    prose = f"- {fact.text} [{index + 1}]"
                    if index in by_index:
                        prose += "\n  **In general:** " + by_index[index]
                    prose += "\n\n"
                    for chunk in self._chunks(prose, [fact.citation_id]):
                        yield chunk
                if self._health_consequential(context):
                    for chunk in self._chunks("For learning only; this is not medical advice.", []):
                        yield chunk
                return
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError):
                self._consecutive_rejections += 1
                if self._consecutive_rejections >= 3:
                    self._retry_after = monotonic() + 120
        if (
            self.model and facts and context.answer_style != "explanation"
            and monotonic() >= self._retry_after
        ):
            try:
                prompt, schema = packet(context, explanatory)
                buffer = ""
                async for token in self.model.tokens(prompt, schema):
                    buffer += token
                    if len(buffer) > 16000:
                        raise ValueError("Response exceeded model output limit")
                blocks = validate_narrative(buffer, context, explanatory)
                self._consecutive_rejections = 0
                self._retry_after = 0.0
                citations: dict[UUID, int] = {}
                for block in blocks:
                    labels = []
                    for citation_id in block.citations:
                        if citation_id not in citations:
                            citations[citation_id] = len(citations) + 1
                        labels.append(f"[{citations[citation_id]}]")
                    prose = block.text + " " + " ".join(labels) + " "
                    for chunk in self._chunks(prose, block.citations):
                        yield chunk
                if self._health_consequential(context):
                    for chunk in self._chunks(
                        "The cited entries describe reported uses or experiments, "
                        "not medical guidance.",
                        [],
                    ):
                        yield chunk
                return
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError):
                self._consecutive_rejections += 1
                if self._consecutive_rejections >= 3:
                    self._retry_after = monotonic() + 120

        response = (
            concise_answer(context, facts) if self.model and facts else None
        ) or await GroundedResponseProvider().generate(request)
        if facts and context.text_evidence:
            cited = set(response.citation_ids)
            notes = reference_facts(context, [fact for fact in facts if fact.citation_id in cited])
            if notes:
                note = notes[0]
                marker = len(response.citation_ids) + 1
                response.text = response.text.rstrip() + (
                    f"\n\nFor context, {note.text} [{marker}]"
                )
                response.citation_ids.append(note.citation_id)
        for chunk in self._chunks(response.text, response.citation_ids, fallback=bool(self.model)):
            yield chunk.model_copy(update={"provider": "grounded", "model": None})

    @staticmethod
    def _health_consequential(context: ResponseContext) -> bool:
        return any(
            evidence.provenance.reference.partition(":")[0]
            in {"GET_THERAPEUTIC_USES", "GET_BIOACTIVITY", "GET_EVIDENCE"}
            for evidence in context.graph_evidence
        )

    def _chunks(
        self, text: str, citations: list[UUID], fallback: bool = False
    ) -> list[ResponseChunk]:
        return [
            ResponseChunk(
                text=text[index : index + 128],
                citation_ids=citations,
                provider=getattr(self.model, "provider_name", "model")
                if self.model
                else "grounded",
                model=self.model.name if self.model else None,
                fallback_used=fallback,
            )
            for index in range(0, len(text), 128)
        ]
