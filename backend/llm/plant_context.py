"""Optional freeform response over a deterministic, plant-scoped graph snapshot."""

import json
from collections.abc import AsyncIterator

import httpx

from backend.contracts.response import FinalResponse, FinalResponseRequest, ResponseChunk
from backend.llm.grounded import GroundedResponseProvider
from backend.llm.ollama import OllamaModel


class PlantContextResponseProvider:
    def __init__(self, model: OllamaModel) -> None:
        self.model = model

    async def generate(self, request: FinalResponseRequest) -> FinalResponse:
        chunks = [chunk async for chunk in self.stream(request)]
        return FinalResponse(
            text="".join(chunk.text for chunk in chunks),
            citation_ids=list(dict.fromkeys(i for chunk in chunks for i in chunk.citation_ids)),
            placeholder=False,
            provider=chunks[-1].provider if chunks else "grounded",
            model=chunks[-1].model if chunks else None,
            fallback_used=any(chunk.fallback_used for chunk in chunks),
        )

    async def stream(self, request: FinalResponseRequest) -> AsyncIterator[ResponseChunk]:
        context = request.response_context
        if (
            context.outcome in {"SAFETY_ABSTENTION", "SCOPE_REJECTED"}
            or not context.resolved_plant
            or not context.plant_context
        ):
            answer = await GroundedResponseProvider().generate(request)
            yield ResponseChunk(text=answer.text, citation_ids=answer.citation_ids,
                                provider="grounded", fallback_used=True)
            return
        prompt = (
            f"You are discussing one plant: {context.resolved_plant.label}.\n"
            "The following is the available plant record snapshot, including node properties "
            "and their relationships. Answer the user's question naturally and helpfully. "
            "You may use your general knowledge for information beyond these records. "
            "The records may be incomplete.\n\n"
            f"Plant records: {json.dumps(context.plant_context, ensure_ascii=False, default=str)}\n"
            f"Snapshot truncated: {context.plant_context_truncated}\n"
            f"User question: {context.user_question}\nAnswer:"
        )
        try:
            output = ""
            async for token in self.model.freeform(prompt):
                output += token
            if not output.strip():
                raise ValueError("Empty model answer")
            for index in range(0, len(output), 128):
                yield ResponseChunk(
                    text=output[index:index + 128],
                    provider="ollama-plant-context",
                    model=self.model.name,
                )
        except (httpx.HTTPError, ValueError, TimeoutError, OSError):
            answer = await GroundedResponseProvider().generate(request)
            yield ResponseChunk(text=answer.text, citation_ids=answer.citation_ids,
                                provider="grounded", fallback_used=True)
