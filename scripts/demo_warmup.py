"""Read-only checks and bounded local model warmup for the demo launcher."""

import sys

import httpx

from backend.config.settings import Settings


def check(client: httpx.Client, path: str, name: str) -> None:
    response = client.get(path)
    response.raise_for_status()
    print(f"Ready: {name}", flush=True)


def main() -> int:
    settings = Settings()
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=12, trust_env=False) as client:
            check(client, "/health", "backend")
            if settings.neo4j_enabled:
                check(client, "/health/neo4j", "Neo4j")
            if settings.text_search_enabled:
                check(client, "/health/postgres", "PostgreSQL")
            if settings.text_semantic_enabled:
                check(client, "/health/qdrant", "Qdrant")
            headers = (
                {"Authorization": f"Bearer {settings.api_key.get_secret_value()}"}
                if settings.api_key else {}
            )
            response = client.get(
                "/api/v1/discovery/autocomplete", params={"q": "neem"}, headers=headers
            )
            response.raise_for_status()
            print("Ready: plant-name search", flush=True)
            capabilities = client.get("/api/v1/capabilities", headers=headers)
            capabilities.raise_for_status()
            if settings.image_enabled and not capabilities.json().get("image_classifier"):
                raise ValueError("Configured image classifier is unavailable")
            if settings.image_enabled:
                print("Ready: image classifier", flush=True)
        if settings.llm_provider == "ollama":
            with httpx.Client(
                base_url=settings.ollama_base_url, timeout=90, trust_env=False
            ) as client:
                response = client.post(
                    "/api/generate",
                    json={
                        "model": settings.llm_model,
                        "prompt": "Reply with OK.",
                        "stream": False,
                        "think": False,
                        "keep_alive": settings.llm_keep_alive,
                        "options": {"num_predict": 8, "temperature": 0},
                    },
                )
                response.raise_for_status()
            print(f"Ready: Ollama model {settings.llm_model}", flush=True)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Warmup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
