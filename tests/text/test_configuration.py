import pytest
from pydantic import SecretStr, ValidationError

from backend.database.search_config import SearchSettings


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:placeholder@localhost:15432/catalog",
        "postgresql://user:placeholder@cloud.example:5432/catalog?sslmode=require",
    ],
)
def test_local_cloud_same_settings(url):
    config = SearchSettings(
        _env_file=None,
        text_search_enabled=True,
        database_url=SecretStr(url),
        qdrant_url="https://cluster.example",
        qdrant_api_key=SecretStr("test-key"),
    )
    assert "placeholder" not in repr(config)
    assert "test-key" not in repr(config)


@pytest.mark.parametrize(
    "values",
    [
        {"text_search_enabled": True},
        {"database_url": "http://wrong.example/database"},
        {"qdrant_url": "https://username:password@host"},
        {"embedding_dimensions": 0},
    ],
)
def test_invalid_configuration_fails_without_values(values):
    with pytest.raises(ValidationError) as error:
        SearchSettings(_env_file=None, **values)
    assert "input_value" not in str(error.value)


def test_disabled_optional_services_allow_blank_example_values():
    config = SearchSettings(
        _env_file=None,
        text_search_enabled=False,
        database_url="",
        qdrant_url="",
        qdrant_api_key="",
    )
    assert config.database_url is None
    assert config.qdrant_url is None
    assert config.qdrant_api_key is None
