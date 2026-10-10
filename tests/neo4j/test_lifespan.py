from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.config.settings import Settings
from backend.database.neo4j.errors import GraphConfigurationError, GraphDatabaseError
from backend.main import create_app


def test_enabled_neo4j_requires_complete_settings():
    with pytest.raises(GraphConfigurationError):
        with TestClient(create_app(Settings(_env_file=None, neo4j_enabled=True))):
            pass


def test_disabled_health_is_explicit():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/health/neo4j")
        assert response.status_code == 503
        assert response.json() == {"status": "disabled"}


def test_one_connection_per_lifespan_and_safe_readiness(monkeypatch):
    connection = MagicMock()
    connection.open = AsyncMock()
    connection.close = AsyncMock()
    connection.config.transaction_timeout_seconds = 10
    factory = MagicMock(return_value=connection)
    client = MagicMock()
    client.health = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.main.Neo4jConnection", factory)
    monkeypatch.setattr("backend.main.Neo4jClient", lambda _: client)
    settings = Settings(
        _env_file=None,
        neo4j_enabled=True,
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="fixture",
        neo4j_password="fixture",
        neo4j_database="fixture",
    )
    with TestClient(create_app(settings)) as http:
        assert http.get("/health/neo4j").status_code == 200
        assert http.get("/health/neo4j").status_code == 200
        assert factory.call_count == 1
        client.health.side_effect = GraphDatabaseError("UNAVAILABLE", "private-detail")
        failed = http.get("/health/neo4j")
        assert failed.status_code == 503
        assert "private-detail" not in failed.text
    connection.close.assert_awaited_once()
