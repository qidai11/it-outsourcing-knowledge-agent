from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
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
    llm_rate_window_seconds: float = 60.0
    llm_rate_limit_wait_timeout_seconds: float = 30.0
    jwt_hs256_secret: SecretStr = SecretStr("replace-me-with-at-least-32-bytes!!")
    jwt_issuer: str = "project-agent"
    jwt_audience: str = "project-agent-api"
    jwt_leeway_seconds: int = 30
    tool_confirmation_ttl_seconds: int = 900

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
        return self
