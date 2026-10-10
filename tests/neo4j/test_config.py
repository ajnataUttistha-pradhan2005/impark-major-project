from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from backend.database.neo4j.config import Neo4jConfig, Neo4jEnvironment, load_neo4j_config
from backend.database.neo4j.errors import GraphConfigurationError


def test_required_environment_without_secret_disclosure():
    settings = Neo4jEnvironment(neo4j_password=SecretStr("private-test-value"), _env_file=None)
    with pytest.raises(GraphConfigurationError) as exc:
        settings.connection_config()
    assert "private-test-value" not in str(exc.value)


@pytest.mark.parametrize(
    "uri",
    [
        "bolt://127.0.0.1:7687",
        "neo4j://localhost:7687",
        "neo4j+s://example.databases.neo4j.io",
        "bolt+s://example.invalid:7687",
    ],
)
def test_supported_environment_uris(uri):
    config = Neo4jConfig(
        uri=uri,
        username=SecretStr("user"),
        password=SecretStr("test-only"),
        database="configured-db",
    )
    assert config.uri == uri
    assert "test-only" not in repr(config)
    assert uri not in repr(config)


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost:7474",
        "neo4j+ssc://unverified.example",
        "bolt://user:secret@host:7687",
        "bolt://",
    ],
)
def test_invalid_connection_uri(uri):
    with pytest.raises(ValidationError):
        Neo4jConfig(
            uri=uri, username=SecretStr("user"), password=SecretStr("secret"), database="db"
        )


def test_dotenv_loading_and_environment_override(monkeypatch, tmp_path: Path):
    for key in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "NEO4J_URI=bolt://localhost:7687\nNEO4J_USERNAME=test-user\n"
        "NEO4J_PASSWORD=test-only\nNEO4J_DATABASE=file-db\n"
    )
    monkeypatch.setenv("NEO4J_DATABASE", "environment-db")
    config = load_neo4j_config(path)
    assert config.database == "environment-db"
    assert config.username.get_secret_value() == "test-user"
    import os

    assert "NEO4J_PASSWORD" not in os.environ


@pytest.mark.parametrize(
    "field,value",
    [
        ("neo4j_transaction_timeout_seconds", 0),
        ("neo4j_max_pool_size", 0),
        ("neo4j_max_result_records", -1),
        ("neo4j_database", ""),
    ],
)
def test_invalid_limits_are_rejected(field, value):
    values = dict(
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="fixture",
        neo4j_password="fixture",
        neo4j_database="fixture",
    )
    values[field] = value
    with pytest.raises(GraphConfigurationError):
        Neo4jEnvironment(_env_file=None, **values).connection_config()
