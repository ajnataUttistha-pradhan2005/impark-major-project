from typing import Protocol

from backend.contracts.response import FinalResponse, FinalResponseRequest


class LLMProvider(Protocol):
    """No tools, repositories, runtime state or action inputs in this contract."""

    async def generate(self, request: FinalResponseRequest) -> FinalResponse: ...


class PlaceholderProvider:
    async def generate(self, request: FinalResponseRequest) -> FinalResponse:
        context = request.response_context
        return FinalResponse(
            text=(
                "IMPARK foundation: response generation is not configured. "
                f"Outcome: {context.outcome}. Educational use only; not medical advice."
            )
        )
