from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    llm_mode: Literal["mock", "openai"] = "mock"
    data_backend: Literal["mock", "mysql"] = "mock"
    embedding_mode: Literal["mock", "openai"] = "mock"
    demo_now: datetime = datetime(2026, 10, 11, 9, tzinfo=UTC)
    default_timezone: str = "Asia/Shanghai"
    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_model: str = "replace-with-served-model-id"
    llm_api_key: SecretStr = SecretStr("EMPTY")
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    agent_timeout_seconds: float = Field(default=35, gt=0, le=180)
    agent_recursion_limit: int = Field(default=16, ge=4, le=32)
    mysql_readonly_uri: SecretStr = SecretStr("")
    sql_max_rows: int = Field(default=200, ge=1, le=1000)
    sql_timeout_ms: int = Field(default=3000, ge=1, le=10000)
    rag_top_k: int = Field(default=8, ge=1, le=50)
    rag_rerank_top_k: int = Field(default=4, ge=1, le=10)
    embedding_base_url: str = "http://127.0.0.1:8000/v1"
    embedding_model: str = ""
    embedding_api_key: SecretStr = SecretStr("EMPTY")
    knowledge_dir: Path = ROOT / "data" / "knowledge"
    knowledge_upload_dir: Path = ROOT / "data" / "uploads"
    persistence_backend: Literal["none", "memory", "postgres"] = "none"
    checkpoint_postgres_uri: SecretStr = SecretStr("")
    api_auth_token: SecretStr = SecretStr("")
    api_admin_token: SecretStr = SecretStr("")
    enable_demo_api: bool = True
    retention_days: int = Field(default=30, ge=1, le=365)
    request_timeout_seconds: float = Field(default=180, gt=0, le=600)
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=20 * 1024 * 1024)

    @field_validator("default_timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("demo_now")
    @classmethod
    def aware_now(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("DEMO_NOW must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def required_live_configuration(self):
        if self.llm_mode == "openai" and self.llm_model == "replace-with-served-model-id":
            raise ValueError("Set LLM_MODEL before enabling openai mode")
        if self.data_backend == "mysql" and not self.mysql_readonly_uri.get_secret_value():
            raise ValueError("MYSQL_READONLY_URI is required for mysql mode")
        if self.embedding_mode == "openai" and not self.embedding_model:
            raise ValueError("EMBEDDING_MODEL is required for openai embeddings")
        if (
            self.persistence_backend == "postgres"
            and not self.checkpoint_postgres_uri.get_secret_value()
        ):
            raise ValueError("CHECKPOINT_POSTGRES_URI is required for postgres persistence")
        if self.environment == "production" and (
            not self.api_auth_token.get_secret_value() or self.enable_demo_api
        ):
            raise ValueError("Production requires API_AUTH_TOKEN and ENABLE_DEMO_API=false")
        return self
