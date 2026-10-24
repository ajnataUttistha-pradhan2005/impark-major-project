"""Configuration settings for the standalone evaluation service."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvaluationConfig(BaseSettings):
    """Configuration for evaluation storage, timeouts, and datasets."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr | None = Field(default=None, alias="DATABASE_URL")
    postgres_pool_size: int = Field(default=5, ge=1, le=20)
    store_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    store_max_records: int = Field(default=1000, ge=1, le=50000)
    ground_truth_path: Path | None = Field(default=None, alias="EVALUATION_GROUND_TRUTH_PATH")

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_optional(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        parsed = urlsplit(value.get_secret_value())
        if parsed.scheme not in {"postgresql", "postgres"}:
            raise ValueError(
                f"Unsupported database scheme: {parsed.scheme!r}. Expected postgresql:// or postgres://"
            )
        return value
