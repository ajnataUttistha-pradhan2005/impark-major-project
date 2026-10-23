"""Regression checks for the teammate demo preflight."""

import sys
from types import SimpleNamespace

from scripts import demo_preflight, demo_warmup
from scripts.demo_preflight import missing_settings


def configured() -> dict[str, str]:
    return {
        "AGENT_MAIN_MODEL": "gemma4:e4b",
        "AGENT_MAIN_MODEL_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "NEO4J_ENABLED": "true",
        "NEO4J_URI": "bolt://127.0.0.1:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "example-only",
        "NEO4J_DATABASE": "neo4j",
        "TEXT_SEARCH_ENABLED": "true",
        "DATABASE_URL": "postgresql://example:example@127.0.0.1:15432/example",
        "QDRANT_URL": "http://127.0.0.1:6333",
        "POSTGRES_USER": "example",
        "POSTGRES_PASSWORD": "example",
        "POSTGRES_DB": "example",
    }


def test_preflight_locates_repo_env_from_scripts_directory(monkeypatch, tmp_path) -> None:
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (root / ".env").write_text(
        "\n".join(f"{key}={value}" for key, value in configured().items()),
        encoding="utf-8",
    )
    seen: list[object] = []
    monkeypatch.setattr(demo_preflight, "__file__", str(scripts / "demo_preflight.py"))
    monkeypatch.setattr(
        demo_preflight, "Settings", lambda **kwargs: seen.append(kwargs["_env_file"])
    )
    monkeypatch.setattr(sys, "argv", ["demo_preflight.py", "--local-docker"])
    monkeypatch.chdir(scripts)

    assert demo_preflight.main() == 0
    assert seen == [root / ".env"]


def test_local_demo_requires_compose_credentials(monkeypatch) -> None:
    for name in configured():
        monkeypatch.delenv(name, raising=False)
    values = configured()
    assert missing_settings(values, local_docker=True) == []
    values["POSTGRES_PASSWORD"] = ""
    assert missing_settings(values, local_docker=True) == ["POSTGRES_PASSWORD"]
    assert missing_settings(values, local_docker=False) == []


def test_demo_rejects_disabled_stores_and_missing_model(monkeypatch) -> None:
    for name in configured():
        monkeypatch.delenv(name, raising=False)
    values = configured()
    values["AGENT_MAIN_MODEL"] = ""
    values["NEO4J_ENABLED"] = "false"
    values["TEXT_SEARCH_ENABLED"] = "false"
    values["OLLAMA_BASE_URL"] = ""
    missing = missing_settings(values, local_docker=False)
    assert "AGENT_MAIN_MODEL or LLM_MODEL" in missing
    assert "NEO4J_ENABLED=true" in missing
    assert "TEXT_SEARCH_ENABLED=true" in missing
    assert "OLLAMA_BASE_URL" in missing


def test_warmup_uses_active_agent_model_without_unconfigured_qdrant(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, bool]:
            return {"image_classifier": False}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            calls.append(("client", kwargs["base_url"]))

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def get(self, path: str, **kwargs: object) -> FakeResponse:
            calls.append(("get", path))
            return FakeResponse()

        def post(self, path: str, **kwargs: object) -> FakeResponse:
            calls.append(("post", kwargs["json"]))
            return FakeResponse()

    settings = SimpleNamespace(
        neo4j_enabled=False,
        text_search_enabled=False,
        text_semantic_enabled=True,
        image_enabled=False,
        api_key=None,
        agent_main_model_provider="ollama",
        agent_main_model="gemma4:e4b",
        llm_model=None,
        ollama_base_url=None,
        llm_keep_alive="5m",
    )
    monkeypatch.setattr(demo_warmup, "Settings", lambda: settings)
    monkeypatch.setattr(demo_warmup.httpx, "Client", FakeClient)
    assert demo_warmup.main() == 0
    assert ("get", "/health/qdrant") not in calls
    assert any(kind == "post" and payload["model"] == "gemma4:e4b" for kind, payload in calls)
