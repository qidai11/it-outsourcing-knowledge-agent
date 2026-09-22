from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.object_store import InMemoryObjectStore

from project_agent.config import Settings
from project_agent.infrastructure.auth.jwt import JwtIdentityVerifier
from project_agent.main import create_app
from project_agent.observability.metrics import ObservabilityMetrics
from project_agent.runtime.api import ApiRuntime

SECRET = "s" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://x:x@127.0.0.1/x",
        local_storage_root=tmp_path,
        ragflow_base_url="http://ragflow.invalid",
        ragflow_api_key=SecretStr("ragflow-test-key"),
        ragflow_expected_version="v0",
        llm_base_url="http://llm.invalid",
        llm_api_key=SecretStr("llm-test-key"),
        llm_model_alias="fake-model",
        llm_request_capacity=1,
        llm_token_capacity=1000,
        jwt_hs256_secret=SecretStr(SECRET),
    )


def _factory(settings: Settings):
    @asynccontextmanager
    async def factory(resolved: Settings) -> AsyncIterator[ApiRuntime]:
        yield ApiRuntime(
            settings=resolved,
            engine=cast(AsyncEngine, object()),
            session_factory=cast(async_sessionmaker[AsyncSession], object()),
            object_store=InMemoryObjectStore(),
            knowledge=FakeKnowledgePort(),
            jwt_verifier=JwtIdentityVerifier(
                secret=SECRET,
                issuer=resolved.jwt_issuer,
                audience=resolved.jwt_audience,
                leeway_seconds=0,
            ),
        )
    return factory


def test_metrics_endpoint_exposes_http_metrics_without_auth(tmp_path: Path) -> None:
    metrics = ObservabilityMetrics()
    settings = _settings(tmp_path)
    app = create_app(settings, runtime_factory=_factory(settings), metrics=metrics)
    with TestClient(app) as client:
        assert client.get("/live").status_code == 200
        response = client.get("/metrics")
    assert response.status_code == 200
    expected = (
        'project_agent_http_requests_total'
        '{method="GET",route="/live",status_code="200"} 1.0'
    )
    assert expected in response.text


def test_dynamic_run_uuid_is_not_used_as_metric_route_label(tmp_path: Path) -> None:
    metrics = ObservabilityMetrics()
    settings = _settings(tmp_path)
    app = create_app(settings, runtime_factory=_factory(settings), metrics=metrics)
    run_id = UUID("77777777-7777-4777-8777-777777777777")
    with TestClient(app) as client:
        client.get(f"/api/v1/runs/{run_id}")
        rendered = client.get("/metrics").text
    assert str(run_id) not in rendered
    assert '/api/v1/runs/{run_id}' in rendered


def test_app_metric_registries_are_isolated(tmp_path: Path) -> None:
    left_metrics = ObservabilityMetrics()
    right_metrics = ObservabilityMetrics()
    settings = _settings(tmp_path)
    left = create_app(settings, runtime_factory=_factory(settings), metrics=left_metrics)
    create_app(settings, runtime_factory=_factory(settings), metrics=right_metrics)
    with TestClient(left) as client:
        client.get("/live")
    assert 'route="/live"' in left_metrics.render_latest().decode()
    assert 'route="/live"' not in right_metrics.render_latest().decode()
