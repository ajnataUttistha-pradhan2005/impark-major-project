"""Single configuration boundary shared by the application, CLI and tests."""

import os
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.database.neo4j.errors import GraphConfigurationError


class Neo4jConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    uri: str = Field(min_length=1, repr=False)
    username: SecretStr = Field(repr=False)
    password: SecretStr = Field(repr=False)
    database: str = Field(min_length=1)
    transaction_timeout_seconds: float = Field(default=10, gt=0, le=300)
    connection_timeout_seconds: float = Field(default=5, gt=0, le=60)
    acquisition_timeout_seconds: float = Field(default=10, gt=0, le=120)
    max_pool_size: int = Field(default=20, ge=1, le=100)
    max_result_records: int = Field(default=1000, ge=1, le=10000)
    allow_writes: bool = False

    @model_validator(mode="after")
    def valid_connection(self) -> Self:
        uri = urlsplit(self.uri)
        if (
            uri.scheme not in {"bolt", "bolt+s", "neo4j", "neo4j+s"}
            or not uri.hostname
            or uri.username
            or uri.password
            or uri.fragment
            or uri.path not in {"", "/"}
        ):
            raise ValueError("Use a Bolt/Neo4j URI without embedded credentials")
        if not self.username.get_secret_value().strip() or not self.password.get_secret_value():
            raise ValueError("Neo4j credentials must be non-empty")
        if not self.database.strip() or self.database != self.database.strip():
            raise ValueError("Neo4j database must be non-empty without surrounding whitespace")
        return self


class Neo4jEnvironment(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)
    neo4j_enabled: bool = False
    neo4j_uri: str | None = Field(default=None, repr=False)
    neo4j_username: SecretStr | None = Field(default=None, repr=False)
    neo4j_password: SecretStr | None = Field(default=None, repr=False)
    neo4j_database: str | None = None
    neo4j_transaction_timeout_seconds: float = 10
    neo4j_connection_timeout_seconds: float = 5
    neo4j_acquisition_timeout_seconds: float = 10
    neo4j_max_pool_size: int = 20
    neo4j_max_result_records: int = 1000
    neo4j_allow_writes: bool = False

    def connection_config(self) -> Neo4jConfig:
        try:
            return Neo4jConfig(
                uri=self.neo4j_uri or "",
                username=self.neo4j_username or SecretStr(""),
                password=self.neo4j_password or SecretStr(""),
                database=self.neo4j_database or "",
                transaction_timeout_seconds=self.neo4j_transaction_timeout_seconds,
                connection_timeout_seconds=self.neo4j_connection_timeout_seconds,
                acquisition_timeout_seconds=self.neo4j_acquisition_timeout_seconds,
                max_pool_size=self.neo4j_max_pool_size,
                max_result_records=self.neo4j_max_result_records,
                allow_writes=self.neo4j_allow_writes,
            )
        except (ValidationError, ValueError):
            raise GraphConfigurationError() from None


def load_neo4j_config(env_file: str | Path = ".env") -> Neo4jConfig:
    """Environment overrides dotenv; never search parent directories for credentials."""
    file_values = dotenv_values(dotenv_path=env_file)
    values = {
        name: os.environ.get(name.upper(), file_values.get(name.upper()))
        for name in Neo4jEnvironment.model_fields
        if name.upper() in os.environ or name.upper() in file_values
    }
    try:
        return Neo4jEnvironment.model_validate(values).connection_config()
    except ValidationError:
        raise GraphConfigurationError() from None
