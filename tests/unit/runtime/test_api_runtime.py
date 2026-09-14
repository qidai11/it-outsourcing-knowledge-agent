from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.object_store import InMemoryObjectStore

from project_agent.config import Settings
from project_agent.infrastructure.auth.jwt import JwtIdentityVerifier
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.object_store.local import LocalFileObjectStoreAdapter
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.main import create_app
from project_agent.runtime.api import ApiRuntime, build_api_runtime


def make_settings(*, database_url: str, local_storage_root: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        local_storage_root=local_storage_root,
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


@pytest.mark.asyncio
async def test_build_api_runtime_constructs_api_resources_without_network(tmp_path: Path) -> None:
    settings = make_settings(
        database_url=(
            "postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent"
        ),
        local_storage_root=tmp_path,
    )

    async with build_api_runtime(settings) as runtime:
        assert runtime.settings is settings
        assert runtime.engine.url.render_as_string(hide_password=False) == settings.database_url
        assert isinstance(runtime.object_store, LocalFileObjectStoreAdapter)
        assert isinstance(runtime.knowledge, RagflowAdapter)
        assert isinstance(runtime.jwt_verifier, JwtIdentityVerifier)


def test_create_app_enters_and_exits_injected_runtime_factory(tmp_path: Path) -> None:
    settings = make_settings(
        database_url=(
            "postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent"
        ),
        local_storage_root=tmp_path,
    )
    entered = False
    exited = False

    @asynccontextmanager
    async def fake_factory(resolved: Settings) -> AsyncIterator[ApiRuntime]:
        nonlocal entered, exited
        entered = True
        engine = create_engine(resolved.database_url)
        try:
            yield ApiRuntime(
                settings=resolved,
                engine=engine,
                session_factory=create_session_factory(engine),
                object_store=InMemoryObjectStore(),
                knowledge=FakeKnowledgePort(),
                jwt_verifier=JwtIdentityVerifier(
                    secret="s" * 32,
                    issuer=resolved.jwt_issuer,
                    audience=resolved.jwt_audience,
                ),
            )
        finally:
            exited = True
            await engine.dispose()

    with TestClient(create_app(settings, runtime_factory=fake_factory)) as client:
        assert entered is True
        assert exited is False
        assert client.app.state.runtime.settings is settings

    assert exited is True
