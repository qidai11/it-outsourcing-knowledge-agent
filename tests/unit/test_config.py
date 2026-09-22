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
    assert settings.llm_request_timeout_seconds == 30.0
    assert settings.llm_max_attempts == 3


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


def test_worker_document_jobs_are_disabled_by_default() -> None:
    settings = Settings(**_settings_kwargs())

    assert settings.worker_ingest_document_enabled is False
    assert settings.worker_delete_document_enabled is False


def test_llm_http_settings_accept_overrides() -> None:
    values = _settings_kwargs()
    values["llm_request_timeout_seconds"] = 12.5
    values["llm_max_attempts"] = 5

    settings = Settings(**values)

    assert settings.llm_request_timeout_seconds == 12.5
    assert settings.llm_max_attempts == 5


def test_settings_default_log_level_is_info() -> None:
    settings = Settings(**_settings_kwargs())

    assert settings.log_level == "INFO"


def test_settings_rejects_unknown_log_level() -> None:
    with pytest.raises(ValidationError):
        Settings(**_settings_kwargs(), log_level="TRACE")


def test_ws6_metrics_and_cost_settings_defaults() -> None:
    settings = Settings(**_settings_kwargs())

    assert settings.worker_metrics_enabled is True
    assert settings.worker_metrics_host == "127.0.0.1"
    assert settings.worker_metrics_port == 9101
    assert settings.llm_input_cost_microunits_per_million_tokens is None
    assert settings.llm_output_cost_microunits_per_million_tokens is None
    assert settings.cost_currency == "USD"


def test_cost_rates_must_be_configured_as_a_pair() -> None:
    with pytest.raises(ValidationError, match="both configured or both omitted"):
        Settings(
            **_settings_kwargs(),
            llm_input_cost_microunits_per_million_tokens=100,
        )


def test_cost_rates_reject_negative_values() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **_settings_kwargs(),
            llm_input_cost_microunits_per_million_tokens=-1,
            llm_output_cost_microunits_per_million_tokens=100,
        )


def test_worker_metrics_port_must_be_valid() -> None:
    with pytest.raises(ValidationError):
        Settings(**_settings_kwargs(), worker_metrics_port=0)
    with pytest.raises(ValidationError):
        Settings(**_settings_kwargs(), worker_metrics_port=65536)


def test_cost_currency_is_normalized_and_must_be_three_ascii_letters() -> None:
    settings = Settings(**_settings_kwargs(), cost_currency="usd")
    assert settings.cost_currency == "USD"

    for invalid in ("US", "USDD", "12D", "美元"):
        with pytest.raises(ValidationError, match="three ASCII letters"):
            Settings(**_settings_kwargs(), cost_currency=invalid)
