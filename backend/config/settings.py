from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.state.models import Budgets


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    application_env: str = "development"
    enable_development_api: bool = False
    cors_origins: list[str] = Field(default_factory=list)
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    neo4j_uri: str | None = None
    neo4j_username: SecretStr | None = None
    neo4j_password: SecretStr | None = None
    qdrant_url: str | None = None
    llm_provider: str = "placeholder"
    llm_model: str | None = None
    ollama_base_url: str | None = None
    vllm_base_url: str | None = None
    trace_buffer_size: int = Field(default=1024, ge=1, le=100000)
    trace_shutdown_seconds: float = Field(default=1, gt=0, le=10)
    max_iterations: int = Field(default=8, ge=1, le=8)
    max_agent_retries: int = Field(default=2, ge=0, le=2)
    repeated_action_threshold: int = Field(default=2, ge=1, le=2)
    max_clarifications: int = Field(default=2, ge=0, le=2)
    entity_auto_resolve_threshold: float = Field(default=0.95, ge=0.8, le=1)
    max_image_bytes: int = Field(default=5_242_880, ge=1, le=5_242_880)
    max_image_pixels: int = Field(default=16_000_000, ge=1, le=16_000_000)

    def budgets(self) -> Budgets:
        return Budgets(
            max_iterations=self.max_iterations,
            max_agent_retries=self.max_agent_retries,
            repeated_action_threshold=self.repeated_action_threshold,
            max_clarifications=self.max_clarifications,
        )
