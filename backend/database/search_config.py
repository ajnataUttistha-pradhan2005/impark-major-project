"""Environment-only configuration shared by local and cloud search stores."""

from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    text_search_enabled: bool = False
    database_url: SecretStr | None = None
    postgres_pool_size: int = Field(default=5, ge=1, le=30)
    store_timeout_seconds: float = Field(default=10, gt=0, le=60)
    store_max_records: int = Field(default=10000, ge=1, le=100000)
    qdrant_url: str | None = Field(default=None, repr=False)
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "plant_names_v1"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimensions: int = Field(default=384, ge=1, le=4096)
    embedding_cache_dir: str = "data/model-cache"
    text_semantic_enabled: bool = True

    @field_validator(
        "database_url",
        "qdrant_url",
        "qdrant_api_key",
        mode="before",
    )
    @classmethod
    def empty_optional(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url")
    @classmethod
    def database_uri(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            parsed = urlsplit(value.get_secret_value())
            if (
                parsed.scheme not in {"postgresql", "postgres"}
                or not parsed.hostname
                or not parsed.path.strip("/")
            ):
                raise ValueError("DATABASE_URL must be a PostgreSQL URI with a database")
        return value

    @field_validator("qdrant_url")
    @classmethod
    def service_uri(cls, value: str | None) -> str | None:
        if value is not None:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Service URL must be HTTP(S) without embedded credentials")
        return value

    @model_validator(mode="after")
    def required(self) -> "SearchSettings":
        if self.text_search_enabled:
            if not self.database_url:
                raise ValueError("DATABASE_URL is required for text search")
            if self.text_semantic_enabled and not self.qdrant_url:
                raise ValueError("QDRANT_URL is required for semantic search")
        return self
