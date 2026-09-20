from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging"]
    database_url: str
    local_storage_root: Path
    ragflow_base_url: str
    ragflow_api_key: SecretStr
    ragflow_expected_version: str
    llm_base_url: str
    llm_api_key: SecretStr
    llm_model_alias: str
    llm_request_timeout_seconds: float = 30.0
    llm_max_attempts: int = 3
    sandbox_tracker_enabled: bool = True
    ragflow_parse_concurrency: int = 2
    ragflow_embedding_model: str | None = None
    ragflow_chunk_method: str = "naive"
    ragflow_request_timeout_seconds: float = 30.0
    ragflow_max_attempts: int = 3
    llm_request_capacity: int
    llm_token_capacity: int
    prompt_cache_ttl_seconds: int = 30
    retention_sweep_enabled: bool = True
    retention_sweep_dry_run: bool = True
    worker_concurrency: int = 4
    worker_claim_limit: int = 4
    worker_lease_seconds: float = 60.0
    worker_heartbeat_seconds: float = 15.0
    worker_poll_seconds: float = 1.0
    worker_retry_base_seconds: float = 5.0
    worker_retry_max_seconds: float = 300.0
    worker_ingest_document_enabled: bool = False
    worker_delete_document_enabled: bool = False
    llm_rate_window_seconds: float = 60.0
    llm_rate_limit_wait_timeout_seconds: float = 30.0
    jwt_hs256_secret: SecretStr = SecretStr("replace-me-with-at-least-32-bytes!!")
    jwt_issuer: str = "project-agent"
    jwt_audience: str = "project-agent-api"
    jwt_leeway_seconds: int = 30
    tool_confirmation_ttl_seconds: int = 900
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    worker_metrics_enabled: bool = True
    worker_metrics_host: str = "127.0.0.1"
    worker_metrics_port: int = Field(default=9101, ge=1, le=65535)
    llm_input_cost_microunits_per_million_tokens: int | None = Field(default=None, ge=0)
    llm_output_cost_microunits_per_million_tokens: int | None = Field(default=None, ge=0)
    cost_currency: str = "USD"

    @model_validator(mode="after")
    def reject_in_memory_database_in_staging(self) -> Self:
        normalized = self.database_url.lower().replace(" ", "")
        is_in_memory = ":memory:" in normalized or "mode=memory" in normalized
        if self.app_env == "staging" and is_in_memory:
            raise ValueError("staging cannot use an in-memory database")
        jwt_secret = self.jwt_hs256_secret.get_secret_value()
        if self.app_env == "staging" and (
            len(jwt_secret.encode("utf-8")) < 32 or jwt_secret.startswith("replace-me")
        ):
            raise ValueError("staging requires a non-default JWT secret of at least 32 bytes")

        input_rate = self.llm_input_cost_microunits_per_million_tokens
        output_rate = self.llm_output_cost_microunits_per_million_tokens
        if (input_rate is None) != (output_rate is None):
            raise ValueError(
                "input and output token prices must be both configured or both omitted"
            )

        normalized_currency = self.cost_currency.strip().upper()
        if (
            len(normalized_currency) != 3
            or not normalized_currency.isascii()
            or not normalized_currency.isalpha()
        ):
            raise ValueError("cost currency must be exactly three ASCII letters")
        self.cost_currency = normalized_currency
        return self


def load_settings() -> Settings:
    """Load settings from BaseSettings sources such as environment variables and .env."""

    settings_factory = cast(Callable[[], Settings], Settings)
    return settings_factory()
