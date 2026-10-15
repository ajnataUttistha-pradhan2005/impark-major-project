from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.config.settings import Settings
from backend.main import create_app


def test_shared_workspace_bearer_and_development_routes_are_protected():
    config = Settings(
        _env_file=None, enable_development_api=True, api_key=SecretStr("test-only-workspace-token")
    )
    with TestClient(create_app(config)) as client:
        for route in ("/api/v1/capabilities", "/dev/discovery/autocomplete?q=neem"):
            assert client.get(route).status_code == 401
            assert client.get(route, headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert (
                client.get(
                    route, headers={"Authorization": "Bearer test-only-workspace-token"}
                ).status_code
                == 200
            )


def test_public_api_fails_closed_without_explicit_local_bypass():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/api/v1/capabilities").status_code == 403
    with TestClient(create_app(Settings(_env_file=None, enable_development_api=True))) as client:
        assert client.get("/api/v1/capabilities").status_code == 200
        assert client.post("/api/v1/conversations", json={}).status_code == 503


def test_cors_allows_frontend_stream_headers_only_for_configured_origin():
    config = Settings(_env_file=None, cors_origins=["http://localhost:3000"])
    with TestClient(create_app(config)) as client:
        response = client.options(
            "/api/v1/conversations",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type,Last-Event-ID",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        response = client.options(
            "/api/v1/conversations",
            headers={
                "Origin": "http://unconfigured.invalid",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 400
