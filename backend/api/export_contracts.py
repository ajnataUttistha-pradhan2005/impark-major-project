"""Export public API and SSE schemas without connecting to any service."""

import json
from pathlib import Path

from backend.api.schemas.platform import StreamEvent
from backend.config.settings import Settings
from backend.main import create_app


def export(directory: Path) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    schema = create_app(settings).openapi()
    schema["paths"] = {
        key: value
        for key, value in schema["paths"].items()
        if key.startswith("/api/v1") or key.startswith("/health")
    }
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("openapi.json", schema),
        ("stream-event.schema.json", StreamEvent.model_json_schema()),
    ):
        (directory / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export(Path("frontend/contracts"))
