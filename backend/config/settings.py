from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import SettingsConfigDict

from backend.database.neo4j.config import Neo4jEnvironment
from backend.database.search_config import SearchSettings
from backend.state.models import Budgets


class Settings(Neo4jEnvironment, SearchSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    application_env: str = "development"
    enable_development_api: bool = False
    cors_origins: list[str] = Field(default_factory=list)
    redis_url: SecretStr | None = None
    llm_provider: Literal["placeholder", "grounded", "ollama"] = "placeholder"
    llm_model: str | None = None
    ollama_base_url: str | None = None
    vllm_base_url: str | None = None
    llm_context_tokens: int = Field(default=4096, ge=1024, le=8192)
    llm_output_tokens: int = Field(default=512, ge=64, le=2048)
    llm_timeout_seconds: float = Field(default=35, gt=0, le=120)
    llm_keep_alive: str = "5m"
    text_intent_model_enabled: bool = True
    text_intent_timeout_seconds: float = Field(default=12, gt=0, le=30)
    api_key: SecretStr | None = None
    max_active_runs: int = Field(default=4, ge=1, le=16)
    max_session_images: int = Field(default=10, ge=1, le=50)
    image_enabled: bool = False
    image_model_path: str | None = None
    image_classes_path: str | None = None
    image_manifest_path: str | None = None
    image_collection: str = "plant_images_v1"
    image_strategy: Literal["cnn", "retrieval", "fusion"] = "fusion"
    image_threads: int = Field(default=4, ge=1, le=16)
    image_min_similarity: float = Field(default=0.6, ge=0, le=1)

    @model_validator(mode="after")
    def response_configuration(self) -> Self:
        if self.image_enabled and not (
            self.text_search_enabled
            and self.qdrant_url
            and self.image_model_path
            and self.image_classes_path
            and self.image_manifest_path
        ):
            raise ValueError(
                "Image agent requires persistent stores and configured model artifacts"
            )
        if self.image_collection == self.qdrant_collection:
            raise ValueError("Image and text collections must be distinct")
        if self.text_search_enabled and self.postgres_pool_size < 2:
            raise ValueError("Chat storage requires POSTGRES_POOL_SIZE >= 2 for its process lease")
        if self.llm_provider == "ollama":
            from urllib.parse import urlsplit

            url = urlsplit(self.ollama_base_url or "")
            if not self.llm_model or url.scheme not in {"http", "https"} or not url.hostname:
                raise ValueError("Ollama requires LLM_MODEL and a valid OLLAMA_BASE_URL")
            if url.username or url.password or url.query or url.fragment:
                raise ValueError("Ollama URL must not contain credentials, query or fragment")
            if self.llm_timeout_seconds >= self.action_timeout_seconds:
                raise ValueError("LLM_TIMEOUT_SECONDS must be below ACTION_TIMEOUT_SECONDS")
        return self

    trace_buffer_size: int = Field(default=1024, ge=1, le=100000)
    trace_shutdown_seconds: float = Field(default=1, gt=0, le=10)
    max_iterations: int = Field(default=8, ge=1, le=8)
    max_agent_retries: int = Field(default=2, ge=0, le=2)
    repeated_action_threshold: int = Field(default=2, ge=1, le=2)
    max_clarifications: int = Field(default=2, ge=0, le=2)
    max_action_calls: int = Field(default=6, ge=1, le=8)
    action_timeout_seconds: float = Field(default=45, gt=0, le=60)
    entity_auto_resolve_threshold: float = Field(default=0.95, ge=0.8, le=1)
    max_image_bytes: int = Field(default=5_242_880, ge=1, le=5_242_880)
    max_image_pixels: int = Field(default=16_000_000, ge=1, le=16_000_000)

    def budgets(self) -> Budgets:
        return Budgets(
            max_iterations=self.max_iterations,
            max_agent_retries=self.max_agent_retries,
            repeated_action_threshold=self.repeated_action_threshold,
            max_clarifications=self.max_clarifications,
            max_action_calls=self.max_action_calls,
            action_timeout_seconds=self.action_timeout_seconds,
        )
