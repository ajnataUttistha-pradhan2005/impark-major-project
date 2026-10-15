"""Evidence-locked response generation with incremental, validated streaming.

The model orders pre-rendered evidence blocks. Only exact server-owned blocks reach users;
unconstrained medical paraphrases and raw model tokens never cross the output boundary.
"""

import json
import re
from collections.abc import AsyncIterator
from uuid import UUID

import httpx

from backend.contracts.response import FinalResponse, FinalResponseRequest, ResponseChunk
from backend.llm.grounded import GroundedResponseProvider
from backend.llm.ollama import TokenModel


class GuardedResponseProvider:
    def __init__(self, model: TokenModel | None = None) -> None:
        self.model = model

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
        blocks: dict[str, tuple[str, UUID]] = {}
        for index, evidence in enumerate(context.graph_evidence[:8]):
            isolated = context.model_copy(
                update={
                    "graph_evidence": [evidence],
                    "uncertainties": [],
                    "resolved_plant": None,
                }
            )
            rendered = await GroundedResponseProvider().generate(
                FinalResponseRequest(response_context=isolated)
            )
            body = rendered.text.rsplit("\nEducational use only;", 1)[0]
            blocks[f"b{index}"] = (body + "\n\n", evidence.evidence_id)
        if context.resolved_plant:
            for chunk in self._chunks(f"For {context.resolved_plant.label}:\n\n", []):
                yield chunk
        emitted: set[str] = set()
        fallback = False
        if self.model:
            schema: dict[str, object] = {
                "type": "object",
                "properties": {
                    "blocks": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(blocks)},
                        "minItems": len(blocks),
                        "maxItems": len(blocks),
                    }
                },
                "required": ["blocks"],
                "additionalProperties": False,
            }
            prompt = json.dumps(
                {
                    "instruction": "Arrange ALL block IDs into a clear answer. Each exactly once. "
                    'Return {"blocks":[...]} only. Do not change any evidence.',
                    "intent": context.intent,
                    "blocks": {key: value[0][:400] for key, value in blocks.items()},
                },
                ensure_ascii=False,
            )
            buffer = ""
            try:
                async for token in self.model.tokens(prompt, schema):
                    buffer += token
                    if len(buffer) > 16000:
                        raise ValueError("Response plan too long")
                    for key in re.findall(r'"(b[0-9]+)"', buffer):
                        if key in blocks and key not in emitted:
                            emitted.add(key)
                            text, citation = blocks[key]
                            for chunk in self._chunks(text, [citation]):
                                yield chunk
                plan = json.loads(buffer)
                if (
                    set(plan) != {"blocks"}
                    or len(plan["blocks"]) != len(blocks)
                    or (set(plan["blocks"]) != set(blocks))
                ):
                    raise ValueError("Invalid response plan")
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError):
                fallback = True
        for key, (text, citation) in blocks.items():
            if key not in emitted:
                for chunk in self._chunks(text, [citation], fallback):
                    yield chunk
        limitations = list(context.uncertainties)
        if len(context.graph_evidence) > len(blocks):
            limitations.append(
                f"Showing {len(blocks)} of {len(context.graph_evidence)} retrieved "
                "evidence records. Full evidence is available with this turn."
            )
        if limitations:
            for chunk in self._chunks(
                "Limitations: " + "; ".join(limitations) + "\n\n", [], fallback
            ):
                yield chunk
        if fallback and self.model:
            for chunk in self._chunks(
                "Model formatting unavailable; showing verified records.\n\n", [], True
            ):
                yield chunk
        for chunk in self._chunks(
            "Educational use only; not medical advice. Reported uses do not "
            "establish clinical efficacy.",
            [],
            fallback,
        ):
            yield chunk

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
