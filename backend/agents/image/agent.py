import time
from typing import Any

from backend.agents.common.callbacks import emit_agent_end, emit_agent_start
from backend.agents.image.providers import ImageInferenceProvider
from backend.contracts.actions import Capability
from backend.contracts.agents import ImageAgentInput, ImageAgentResult, Observation


class ImageAgent:
    """Image capability adapter. All global state changes remain with the harness."""

    def __init__(self, provider: ImageInferenceProvider | None = None) -> None:
        self.provider = provider

    async def execute(
        self, request: ImageAgentInput, callbacks: Any = None
    ) -> Observation:
        t_start = time.perf_counter()
        run_id = str(request.invocation.correlation.run_id)
        emit_agent_start(
            callbacks, "image_understanding", f"Image: {request.image.image_id}", run_id=run_id
        )

        result = (
            await self.provider.infer(request.image, request.invocation.correlation.session_id)
            if self.provider
            else ImageAgentResult()
        )

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        context_snippets = [e.claim for e in result.evidence] if result.evidence else []
        if not context_snippets and result.candidates:
            context_snippets = [
                f"Image candidate: {c.label} (confidence: {c.confidence:.2f})"
                for c in result.candidates[:3]
            ]

        emit_agent_end(
            callbacks,
            "image_understanding",
            result,
            run_id=run_id,
            latency_ms=elapsed_ms,
            context_snippets=context_snippets,
        )

        return Observation(
            invocation=request.invocation,
            component=Capability.IMAGE,
            payload=result,
        )
