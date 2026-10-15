"""Explicit local model readiness/warm-up command; never downloads models."""

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

from backend.config.settings import Settings
from backend.contracts.evidence import Evidence, Modality, Provenance
from backend.contracts.response import FinalResponseRequest, ResponseContext
from backend.llm.guarded import GuardedResponseProvider
from backend.llm.ollama import OllamaModel


async def run(command: str) -> None:
    settings = Settings()
    if settings.llm_provider != "ollama":
        raise SystemExit("Set LLM_PROVIDER=ollama, LLM_MODEL and OLLAMA_BASE_URL first")
    # Explicit warm-up can allow a cold model more time than an interactive turn.
    model = OllamaModel(
        settings.model_copy(update={"llm_timeout_seconds": 120}) if command == "warm" else settings
    )
    try:
        healthy = await model.health()
        if not healthy:
            raise SystemExit("Configured Ollama model is unavailable; install it explicitly")
        started = perf_counter()
        if command == "benchmark":
            results = []
            for count in (2, 4, 8):
                request = FinalResponseRequest(
                    response_context=ResponseContext(
                        intent="GET_PHYTOCHEMICALS",
                        outcome="Objectives satisfied",
                        graph_evidence=[
                            Evidence(
                                modality=Modality.GRAPH,
                                claim=json.dumps({"compound": f"Synthetic compound {i}"}),
                                confidence=1,
                                provenance=Provenance(
                                    source_id=f"fixture:{i}",
                                    source_type="graph",
                                    reference="Synthetic evaluation record",
                                ),
                            )
                            for i in range(count)
                        ],
                    )
                )
                start = perf_counter()
                response = await GuardedResponseProvider(model).generate(request)
                results.append(
                    {
                        "evidence_count": count,
                        "elapsed_seconds": round(perf_counter() - start, 3),
                        "fallback_used": response.fallback_used,
                        "citation_count": len(response.citation_ids),
                        "model": model.name,
                    }
                )
            target = Path("data/evaluation/response_model_warm_benchmark.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                target.write_text, json.dumps(results, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps(results))
            return
        if command == "warm":
            _ = [
                token
                async for token in model.tokens(
                    'Return {"blocks":["b0"]}',
                    {
                        "type": "object",
                        "properties": {
                            "blocks": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["b0"]},
                                "minItems": 1,
                                "maxItems": 1,
                            }
                        },
                        "required": ["blocks"],
                        "additionalProperties": False,
                    },
                )
            ]
        print(
            json.dumps(
                {
                    "model": model.name,
                    "status": "ready",
                    "elapsed_seconds": round(perf_counter() - started, 3),
                }
            )
        )
    finally:
        await model.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["health", "warm", "benchmark"])
    asyncio.run(run(parser.parse_args().command))
