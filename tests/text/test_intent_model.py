import asyncio
import json

import httpx

from backend.agents.text.intent_model import OllamaIntentModel
from backend.contracts.agents import QueryType


async def test_ollama_intent_model_accepts_only_typed_bounded_suggestions():
    outputs = iter(
        [
            {"query_types": ["GET_DOCUMENTS"], "reuse_previous_topic": False,
             "confidence": 0.92},
            {"query_types": ["COMPARE_PLANTS"], "reuse_previous_topic": False,
             "confidence": 0.99},
            {"query_types": ["GET_PLANT_PART_DETAILS"],
             "reuse_previous_topic": False, "confidence": 0.99},
            {"query_types": ["GET_EVIDENCE"], "reuse_previous_topic": False,
             "confidence": 0.2},
        ]
    )

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is False and payload["think"] is False
        assert "tools" not in payload
        return httpx.Response(200, json={"message": {"content": json.dumps(next(outputs))}})

    model = OllamaIntentModel("http://localhost:11434", "fixture", asyncio.Semaphore(1))
    await model.client.aclose()
    model.client = httpx.AsyncClient(
        base_url="http://localhost:11434", transport=httpx.MockTransport(handle)
    )
    try:
        accepted = await model.suggest("Where was it published?", [], True)
        assert accepted and accepted.query_types == [QueryType.GET_DOCUMENTS]
        assert await model.suggest("compare", [], True) is None
        assert await model.suggest("part details", [], True) is None
        assert await model.suggest("evidence", [], True) is None
    finally:
        await model.close()
