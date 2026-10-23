"""Check demo configuration without connecting to services or printing secrets."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

from backend.config.settings import Settings


def missing_settings(
    values: dict[str, str | None], *, local_docker: bool, root: Path | None = None
) -> list[str]:
    root = root or Path.cwd()

    def value(name: str) -> str:
        return (os.environ.get(name) or values.get(name) or "").strip()

    required = [
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "DATABASE_URL",
        "QDRANT_URL",
    ]
    if local_docker:
        required.extend(("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"))
    missing = [name for name in required if not value(name)]
    if not (value("AGENT_MAIN_MODEL") or value("LLM_MODEL")):
        missing.append("AGENT_MAIN_MODEL or LLM_MODEL")
    if value("NEO4J_ENABLED").lower() not in {"true", "1", "yes"}:
        missing.append("NEO4J_ENABLED=true")
    if value("TEXT_SEARCH_ENABLED").lower() not in {"true", "1", "yes"}:
        missing.append("TEXT_SEARCH_ENABLED=true")
    if value("AGENT_MAIN_MODEL_PROVIDER").lower() == "ollama" and not value("OLLAMA_BASE_URL"):
        missing.append("OLLAMA_BASE_URL")
    if value("IMAGE_ENABLED").lower() in {"true", "1", "yes"}:
        for name in ("IMAGE_MODEL_PATH", "IMAGE_CLASSES_PATH", "IMAGE_MANIFEST_PATH"):
            path = value(name)
            if not path or not (root / path).is_file():
                missing.append(f"{name} (file missing)")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-docker", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.is_file():
        print("Create .env from .env.example before starting the demo.", file=sys.stderr)
        return 1
    values = dotenv_values(env_path)
    missing = missing_settings(values, local_docker=args.local_docker, root=root)
    if missing:
        print("Demo configuration is incomplete: " + ", ".join(missing), file=sys.stderr)
        print(
            "See docs/setup-and-operations/README.md. No credential values were printed.",
            file=sys.stderr,
        )
        return 1
    try:
        Settings(_env_file=env_path)
    except ValueError as error:
        # Pydantic's validation output may include input data; keep the printed error generic.
        print(
            ".env has invalid application settings; check URL formats and enabled features.",
            file=sys.stderr,
        )
        print(f"Validation category: {type(error).__name__}", file=sys.stderr)
        return 1
    print("Demo configuration: ready (values hidden)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
