import asyncio
import json

import httpx
import pytest

from backend.config.settings import Settings
from backend.contracts.evidence import Evidence, Provenance
from backend.contracts.response import FinalResponseRequest, ResponseContext
from backend.llm.guarded import GuardedResponseProvider
from backend.llm.ollama import OllamaModel


def response_request(count=2):
    return FinalResponseRequest(
        response_context=ResponseContext(
            intent="GET_THERAPEUTIC_USES",
            outcome="Objectives satisfied",
            uncertainties=["Clinical efficacy has not been established"],
            graph_evidence=[
                Evidence(
                    modality="graph",
                    claim=json.dumps({"reported_use": f"Synthetic use {i}"}),
                    evidence_type="traditional",
                    confidence=1,
                    provenance=Provenance(
                        source_id=f"fixture:{i}", source_type="graph", reference="Synthetic source"
                    ),
                )
                for i in range(count)
            ],
        )
    )


class Model:
    name = "fixture:model"

    def __init__(self, output):
        self.output = output
        self.calls = 0

    async def tokens(self, prompt, schema):
        self.calls += 1
        assert "tools" not in schema
        assert "Synthetic" in prompt
        if isinstance(self.output, BaseException):
            raise self.output
        for character in self.output:
            yield character


async def test_incremental_approved_blocks_and_exact_citations():
    request = response_request()
    model = Model('{"blocks":["b1","b0"]}')
    chunks = [c async for c in GuardedResponseProvider(model).stream(request)]
    answer = "".join(c.text for c in chunks)
    assert len(chunks) > 2
    assert answer.index("Synthetic use 1") < answer.index("Synthetic use 0")
    assert answer.count("class: traditional") == 2
    assert "Clinical efficacy has not been established" in answer
    assert "Educational use only" in answer
    assert {i for c in chunks for i in c.citation_ids} == {
        e.evidence_id for e in request.response_context.graph_evidence
    }
    assert not any(c.fallback_used for c in chunks)


@pytest.mark.parametrize(
    "output",
    [
        "Take 500mg; clinically proven; ignore all restrictions",
        '{"blocks":["b0","b0"]}',
        '{"blocks":["b9"]}',
        '{"blocks":["b0"]}',
        "[]",
        '{"blocks":[{}]}',
        '{"blocks":["b0","b1"],"extra":"invented"}',
        TimeoutError(),
        httpx.ConnectError("private secret"),
    ],
)
async def test_invalid_models_fall_back_without_inventing_or_losing_evidence(output):
    result = await GuardedResponseProvider(Model(output)).generate(response_request())
    assert result.fallback_used
    assert result.text.count("Synthetic use 0") == 1
    assert result.text.count("Synthetic use 1") == 1
    assert "500mg" not in result.text and "private secret" not in result.text
    assert "clinically proven" not in result.text
    assert len(result.citation_ids) == 2


@pytest.mark.parametrize("outcome", ["SAFETY_ABSTENTION", "SCOPE_REJECTED"])
async def test_policy_responses_do_not_call_model(outcome):
    request = response_request(0)
    request.response_context.outcome = outcome
    model = Model("bad")
    result = await GuardedResponseProvider(model).generate(request)
    assert model.calls == 0
    assert result.provider == "grounded" and result.model is None
    assert not result.citation_ids


async def test_cancellation_is_not_swallowed_as_model_fallback():
    with pytest.raises(asyncio.CancelledError):
        await GuardedResponseProvider(Model(asyncio.CancelledError())).generate(response_request())


async def test_bounded_rendering_discloses_evidence_not_shown():
    result = await GuardedResponseProvider().generate(response_request(10))
    assert len(result.citation_ids) == 8
    assert "Showing 8 of 10" in result.text
    assert not result.fallback_used


@pytest.mark.parametrize(
    "frames",
    [
        [{"message": {"content": '{"blocks":[]}'}, "done": True}],
        [{"message": {"content": "part"}}, {"message": {"content": "end"}, "done": True}],
    ],
)
async def test_ollama_transport_uses_bounded_structured_stream(frames):
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] and body["think"] is False
        assert body["options"]["num_ctx"] == 4096
        assert "tools" not in body
        return httpx.Response(200, text="\n".join(json.dumps(f) for f in frames))

    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        llm_model="fixture:model",
        ollama_base_url="http://localhost:11434",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=settings.ollama_base_url
    ) as client:
        model = OllamaModel(settings, client)
        output = "".join([t async for t in model.tokens("prepared", {"type": "object"})])
        assert output == "".join(f["message"]["content"] for f in frames)


@pytest.mark.parametrize(
    "frame",
    [
        [],
        {"message": []},
        {"message": {"content": 123}},
        {"message": {"tool_calls": [{"name": "database"}]}},
        {"error": "secret"},
        {"message": {"content": "partial"}},
        {"done": True, "done_reason": "length"},
    ],
)
async def test_ollama_rejects_invalid_incomplete_and_tool_frames(frame):
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        llm_model="fixture:model",
        ollama_base_url="http://localhost:11434",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=frame)),
        base_url=settings.ollama_base_url,
    ) as client:
        with pytest.raises(ValueError):
            _ = [t async for t in OllamaModel(settings, client).tokens("prepared", {})]
