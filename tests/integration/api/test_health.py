from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient
from pydantic import SecretStr

from project_agent.config import Settings
from project_agent.main import create_app
from project_agent.runtime.api import ApiRuntime


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=(
            "postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent"
        ),
        local_storage_root=tmp_path,
        ragflow_base_url="http://ragflow.invalid",
        ragflow_api_key=SecretStr("fake-ragflow-key"),
        ragflow_expected_version="fake-version",
        llm_base_url="http://llm.invalid",
        llm_api_key=SecretStr("fake-llm-key"),
        llm_model_alias="fake-model",
        llm_request_capacity=1,
        llm_token_capacity=1000,
        jwt_hs256_secret=SecretStr("s" * 32),
    )


def test_live_does_not_require_external_services(tmp_path: Path) -> None:
    with TestClient(create_app(_test_settings(tmp_path))) as client:
        response = client.get("/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _FakeConnection:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.statements: list[str] = []

    async def __aenter__(self) -> _FakeConnection:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        del exc_type, exc, traceback

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))
        if self.error is not None:
            raise self.error


class _FakeEngine:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.connection = _FakeConnection(error=error)
        self.connect_calls = 0

    def connect(self) -> _FakeConnection:
        self.connect_calls += 1
        return self.connection


def _runtime_factory_with_engine(engine: _FakeEngine):
    @asynccontextmanager
    async def factory(_settings: Settings) -> AsyncIterator[ApiRuntime]:
        runtime = cast(ApiRuntime, SimpleNamespace(engine=engine))
        yield runtime

    return factory


def test_ready_reports_database_ready_without_calling_provider_services(
    tmp_path: Path,
) -> None:
    engine = _FakeEngine()

    with TestClient(
        create_app(
            _test_settings(tmp_path),
            runtime_factory=_runtime_factory_with_engine(engine),
        )
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "configuration": "ok",
        "database": "ok",
    }
    assert engine.connect_calls == 1
    assert engine.connection.statements == ["SELECT 1"]


def test_ready_returns_sanitized_not_ready_when_database_probe_fails(
    tmp_path: Path,
) -> None:
    engine = _FakeEngine(
        error=RuntimeError("postgresql://project_agent:secret@postgres/project_agent")
    )

    with TestClient(
        create_app(
            _test_settings(tmp_path),
            runtime_factory=_runtime_factory_with_engine(engine),
        )
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "configuration": "ok",
        "database": "unavailable",
    }
    assert "postgresql" not in response.text
    assert "secret" not in response.text


def test_invalid_environment_keeps_live_available_and_ready_not_ready(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "LOCAL_STORAGE_ROOT",
        "RAGFLOW_BASE_URL",
        "RAGFLOW_API_KEY",
        "RAGFLOW_EXPECTED_VERSION",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_ALIAS",
        "LLM_REQUEST_CAPACITY",
        "LLM_TOKEN_CAPACITY",
    ):
        monkeypatch.delenv(name, raising=False)
    entered = False

    @asynccontextmanager
    async def must_not_enter(_settings: Settings) -> AsyncIterator[ApiRuntime]:
        nonlocal entered
        entered = True
        raise AssertionError("runtime factory must not run for invalid configuration")
        yield  # pragma: no cover

    with TestClient(create_app(runtime_factory=must_not_enter)) as client:
        live_response = client.get("/live")
        ready_response = client.get("/ready")

    assert entered is False
    assert live_response.status_code == 200
    assert ready_response.status_code == 503
    assert ready_response.json() == {"status": "not_ready", "configuration": "invalid"}
