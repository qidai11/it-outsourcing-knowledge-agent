from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from project_agent.config import Settings


def _settings_kwargs() -> dict[str, object]:
    return {
        "app_env": "development",
        "database_url": "postgresql+asyncpg://agent:agent@localhost:5432/agent",
        "local_storage_root": Path("./data"),
        "ragflow_base_url": "http://localhost:9380",
        "ragflow_api_key": SecretStr("ragflow-test-key"),
        "ragflow_expected_version": "v0-test",
        "llm_base_url": "https://llm.example.test/v1",
        "llm_api_key": SecretStr("llm-test-key"),
        "llm_model_alias": "test-model",
        "llm_request_capacity": 10,
        "llm_token_capacity": 100_000,
    }


def test_settings_load_required_values() -> None:
    settings = Settings(**_settings_kwargs())

    assert settings.app_env == "development"
    assert settings.local_storage_root == Path("data")
    assert settings.sandbox_tracker_enabled is True
    assert settings.ragflow_parse_concurrency == 2
    assert settings.prompt_cache_ttl_seconds == 30
    assert settings.retention_sweep_enabled is True


def test_staging_rejects_in_memory_database() -> None:
    values = _settings_kwargs()
    values["app_env"] = "staging"
    values["database_url"] = "sqlite+aiosqlite:///:memory:"

    with pytest.raises(ValidationError, match="staging cannot use an in-memory database"):
        Settings(**values)


def test_development_allows_in_memory_database_for_tests_and_local_work() -> None:
    values = _settings_kwargs()
    values["database_url"] = "sqlite+aiosqlite:///:memory:"

    settings = Settings(**values)

    assert settings.database_url.endswith(":memory:")


def test_staging_rejects_default_jwt_secret() -> None:
    values = _settings_kwargs()
    values["app_env"] = "staging"
    values["jwt_hs256_secret"] = SecretStr("replace-me-with-at-least-32-bytes!!")

    with pytest.raises(ValidationError, match="staging requires a non-default JWT secret"):
        Settings(**values)
