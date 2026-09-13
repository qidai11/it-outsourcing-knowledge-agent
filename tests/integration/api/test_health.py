from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from project_agent.config import Settings
from project_agent.main import create_app


def _test_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        local_storage_root=Path("./data-test"),
        ragflow_base_url="http://ragflow.invalid",
        ragflow_api_key=SecretStr("fake-ragflow-key"),
        ragflow_expected_version="fake-version",
        llm_base_url="http://llm.invalid",
        llm_api_key=SecretStr("fake-llm-key"),
        llm_model_alias="fake-model",
        llm_request_capacity=1,
        llm_token_capacity=1000,
    )


def test_live_does_not_require_external_services() -> None:
    with TestClient(create_app(_test_settings())) as client:
        response = client.get("/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_configuration_ready_without_calling_external_services() -> None:
    with TestClient(create_app(_test_settings())) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "configuration": "ok"}
