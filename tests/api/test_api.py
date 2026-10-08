import io
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from backend.config.settings import Settings
from backend.main import create_app


def test_health_and_correlation():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        identifier = str(uuid4())
        result = client.get("/health", headers={"X-Correlation-ID": identifier})
        assert result.status_code == 200
        assert result.headers["X-Correlation-ID"] == identifier
        assert client.post("/dev/conversations").status_code == 403


def test_discovery_clarification_and_validation():
    with TestClient(create_app(Settings(_env_file=None, enable_development_api=True))) as client:
        created = client.post("/dev/conversations").json()
        assert created["mode"] == "discovery"
        sid = created["correlation"]["session_id"]
        endpoint = f"/dev/conversations/{sid}/turns"
        bad = client.post(endpoint, json={"text": "secret-value", "cypher": "secret-value"})
        assert bad.status_code == 422
        assert "secret-value" not in bad.text
        first = client.post(endpoint, json={"text": "unknown plant"})
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "WAITING_USER"
        second = client.post(endpoint, json={"text": "more description"}).json()
        assert second["correlation"]["run_id"] == first.json()["correlation"]["run_id"]
        assert client.get(f"/dev/conversations/{sid}/history").status_code == 200
        assert client.get("/dev/discovery/autocomplete?q=plant").json()["implemented"] is False


def test_upload_and_image_only_discovery():
    with TestClient(create_app(Settings(_env_file=None, enable_development_api=True))) as client:
        sid = client.post("/dev/conversations").json()["correlation"]["session_id"]
        endpoint = f"/dev/conversations/{sid}/images"
        assert (
            client.post(
                endpoint, content=b"invalid", headers={"Content-Type": "image/png"}
            ).status_code
            == 422
        )
        content = io.BytesIO()
        Image.new("RGB", (10, 10)).save(content, format="PNG")
        uploaded = client.post(
            endpoint, content=content.getvalue(), headers={"Content-Type": "image/png"}
        )
        assert uploaded.status_code == 201
        result = client.post(
            f"/dev/conversations/{sid}/turns", json={"image_id": uploaded.json()["image_id"]}
        )
        assert result.status_code == 200
        assert result.json()["status"] == "WAITING_USER"


def test_production_cannot_enable_development_bypass():
    settings = Settings(_env_file=None, application_env="production", enable_development_api=True)
    with TestClient(create_app(settings)) as client:
        assert client.post("/dev/conversations").status_code == 403
