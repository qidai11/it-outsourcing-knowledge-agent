from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.object_store import InMemoryObjectStore
from tests.helpers.jwt import make_hs256_token

from project_agent.api.dependencies import get_authenticated_identity
from project_agent.application.services.authorization import AuthenticatedIdentity
from project_agent.config import Settings
from project_agent.infrastructure.auth.jwt import JwtIdentityVerifier
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.main import create_app
from project_agent.runtime.api import ApiRuntime

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
USER_ID = UUID("11111111-1111-4111-8111-111111111111")
SECRET = "s" * 32


def _settings(tmp_path: Path) -> Settings:
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
        jwt_hs256_secret=SecretStr(SECRET),
        jwt_leeway_seconds=0,
    )


def _app(tmp_path: Path):
    settings = _settings(tmp_path)

    @asynccontextmanager
    async def fake_runtime_factory(resolved: Settings) -> AsyncIterator[ApiRuntime]:
        engine = create_engine(resolved.database_url)
        try:
            yield ApiRuntime(
                settings=resolved,
                engine=engine,
                session_factory=create_session_factory(engine),
                object_store=InMemoryObjectStore(),
                knowledge=FakeKnowledgePort(),
                jwt_verifier=JwtIdentityVerifier(
                    secret=SECRET,
                    issuer=resolved.jwt_issuer,
                    audience=resolved.jwt_audience,
                    leeway_seconds=0,
                    clock=lambda: NOW,
                ),
            )
        finally:
            await engine.dispose()

    app = create_app(settings, runtime_factory=fake_runtime_factory)
    router = APIRouter()

    @router.get("/_test/protected")
    async def protected(
        identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    ) -> dict[str, str]:
        return {"user_id": str(identity.user_id)}

    app.include_router(router)
    return app, settings


def _token(
    settings: Settings,
    *,
    secret: str = SECRET,
    expires_at: datetime | None = None,
    **extra,
):
    return make_hs256_token(
        user_id=USER_ID,
        secret=secret,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_at=expires_at or (NOW + timedelta(minutes=5)),
        extra_claims=extra or None,
    )


def test_missing_authorization_header_returns_bearer_401(tmp_path: Path) -> None:
    app, _settings_value = _app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/_test/protected")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_signature_returns_bearer_401(tmp_path: Path) -> None:
    app, settings = _app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/_test/protected",
            headers={"Authorization": f"Bearer {_token(settings, secret='x' * 32)}"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_expired_token_returns_bearer_401(tmp_path: Path) -> None:
    app, settings = _app(tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/_test/protected",
            headers={
                "Authorization": f"Bearer {_token(settings, expires_at=NOW - timedelta(seconds=1))}"
            },
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_valid_token_returns_only_identity_and_discards_forged_authorization_claims(
    tmp_path: Path,
) -> None:
    app, settings = _app(tmp_path)
    forged_project = uuid4()
    token = _token(
        settings,
        role="project_manager",
        project_ids=[str(forged_project)],
    )

    with TestClient(app) as client:
        response = client.get(
            "/_test/protected",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"user_id": str(USER_ID)}
    assert "project_manager" not in response.text
    assert str(forged_project) not in response.text
