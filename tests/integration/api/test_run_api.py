from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.job_queue import FakeJobQueue
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.object_store import InMemoryObjectStore
from tests.fakes.run_repository import FakeRunRepository
from tests.helpers.jwt import make_hs256_token

from project_agent.api.v1.runs import RunApiServices, get_run_api_services
from project_agent.application.services.authorization import (
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.application.services.runs import RunApplicationService
from project_agent.config import Settings
from project_agent.domain.enums import ProjectRole
from project_agent.domain.runs import RunBusinessMode
from project_agent.infrastructure.auth.jwt import JwtIdentityVerifier
from project_agent.main import create_app
from project_agent.runtime.api import ApiRuntime

NOW = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)
SECRET = "s" * 32
COMPANY = UUID("11111111-1111-4111-8111-111111111111")
CLIENT = UUID("22222222-2222-4222-8222-222222222222")
PROJECT = UUID("33333333-3333-4333-8333-333333333333")
OTHER_PROJECT = UUID("44444444-4444-4444-8444-444444444444")
USER = UUID("55555555-5555-4555-8555-555555555555")
OTHER_USER = UUID("66666666-6666-4666-8666-666666666666")


def _membership(*, project_id: UUID = PROJECT) -> MembershipAccessRecord:
    return MembershipAccessRecord(
        company_id=COMPANY,
        client_id=CLIENT,
        project_id=project_id,
        project_code="PRJ-TEST",
        role=ProjectRole.DEVELOPER,
        valid_from=NOW - timedelta(days=1),
        valid_to=None,
    )


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


class RunApiHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.settings = _settings(tmp_path)
        self.auth_repo = FakeProjectAuthorizationRepository()
        self.runs = FakeRunRepository()
        self.jobs = FakeJobQueue()
        self.service = RunApplicationService(
            authorization=AuthorizationService(self.auth_repo, clock=lambda: NOW),
            repository=self.runs,
            jobs=self.jobs,
        )

        @asynccontextmanager
        async def fake_runtime_factory(resolved: Settings) -> AsyncIterator[ApiRuntime]:
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
                    clock=lambda: NOW,
                ),
            )

        self.app = create_app(self.settings, runtime_factory=fake_runtime_factory)
        self.app.dependency_overrides[get_run_api_services] = lambda: RunApiServices(
            runs=self.service,
            repository=self.runs,
        )

    def token(self, *, user_id: UUID = USER, secret: str = SECRET, **claims: object) -> str:
        return make_hs256_token(
            user_id=user_id,
            secret=secret,
            issuer=self.settings.jwt_issuer,
            audience=self.settings.jwt_audience,
            expires_at=NOW + timedelta(minutes=30),
            extra_claims=claims or None,
        )

    def headers(self, *, user_id: UUID = USER, **claims: object) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(user_id=user_id, **claims)}"}

    @staticmethod
    def create_payload(
        *,
        project_id: UUID = PROJECT,
        thread_id: UUID | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "project_id": str(project_id),
            "business_mode": RunBusinessMode.QA.value,
            "query": "deployment window?",
        }
        if thread_id is not None:
            payload["thread_id"] = str(thread_id)
        return payload


def test_create_run_requires_bearer_authentication(tmp_path: Path) -> None:
    h = RunApiHarness(tmp_path)

    with TestClient(h.app) as client:
        missing = client.post("/api/v1/runs", json=h.create_payload())
        invalid = client.post(
            "/api/v1/runs",
            json=h.create_payload(),
            headers={"Authorization": f"Bearer {h.token(secret='x' * 32)}"},
        )

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.status_code == 401
    assert invalid.headers["www-authenticate"] == "Bearer"


def test_active_member_creates_queued_run_without_echoing_forged_claims(tmp_path: Path) -> None:
    h = RunApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT)] = _membership()

    with TestClient(h.app) as client:
        response = client.post(
            "/api/v1/runs",
            json=h.create_payload(),
            headers=h.headers(role="project_manager", project_ids=[str(OTHER_PROJECT)]),
        )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == str(PROJECT)
    assert body["business_mode"] == RunBusinessMode.QA.value
    assert body["status"] == "QUEUED"
    assert body["started_at"] is None
    assert "project_manager" not in response.text
    assert str(OTHER_PROJECT) not in response.text
    assert len(h.jobs.jobs) == 1


def test_forged_claims_do_not_grant_membership(tmp_path: Path) -> None:
    h = RunApiHarness(tmp_path)

    with TestClient(h.app) as client:
        response = client.post(
            "/api/v1/runs",
            json=h.create_payload(),
            headers=h.headers(role="project_manager", project_ids=[str(PROJECT)]),
        )

    assert response.status_code == 403
    assert h.runs.runs == {}
    assert h.jobs.jobs == ()


def test_membership_is_rechecked_and_revocation_denies_next_request(tmp_path: Path) -> None:
    h = RunApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT)] = _membership()
    headers = h.headers()

    with TestClient(h.app) as client:
        first = client.post("/api/v1/runs", json=h.create_payload(), headers=headers)
        h.auth_repo.memberships[(USER, PROJECT)] = replace(_membership(), valid_to=NOW)
        second = client.post("/api/v1/runs", json=h.create_payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 403
    assert len(h.runs.runs) == 1
    assert len(h.jobs.jobs) == 1


def test_existing_thread_from_other_project_or_user_is_forbidden(tmp_path: Path) -> None:
    h = RunApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT)] = _membership()

    async def seed() -> tuple[UUID, UUID]:
        other_project = await h.runs.create_thread(
            company_id=COMPANY,
            project_id=OTHER_PROJECT,
            user_id=USER,
        )
        other_user = await h.runs.create_thread(
            company_id=COMPANY,
            project_id=PROJECT,
            user_id=OTHER_USER,
        )
        return other_project.id, other_user.id

    import asyncio

    other_project_thread, other_user_thread = asyncio.run(seed())

    with TestClient(h.app) as client:
        left = client.post(
            "/api/v1/runs",
            json=h.create_payload(thread_id=other_project_thread),
            headers=h.headers(),
        )
        right = client.post(
            "/api/v1/runs",
            json=h.create_payload(thread_id=other_user_thread),
            headers=h.headers(),
        )

    assert left.status_code == 403
    assert right.status_code == 403


def test_get_run_is_current_membership_scoped_and_unknown_is_404(tmp_path: Path) -> None:
    h = RunApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT)] = _membership()

    with TestClient(h.app) as client:
        created = client.post("/api/v1/runs", json=h.create_payload(), headers=h.headers())
        run_id = created.json()["run_id"]
        own = client.get(f"/api/v1/runs/{run_id}", headers=h.headers())
        unknown = client.get(
            "/api/v1/runs/77777777-7777-4777-8777-777777777777",
            headers=h.headers(),
        )
        h.auth_repo.memberships[(USER, PROJECT)] = replace(_membership(), valid_to=NOW)
        revoked = client.get(f"/api/v1/runs/{run_id}", headers=h.headers())

    assert own.status_code == 200
    assert own.json()["run_id"] == run_id
    assert unknown.status_code == 404
    assert revoked.status_code == 403


def test_get_cross_project_run_without_membership_is_forbidden(tmp_path: Path) -> None:
    h = RunApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, OTHER_PROJECT)] = _membership(project_id=OTHER_PROJECT)

    async def seed() -> UUID:
        thread = await h.runs.create_thread(
            company_id=COMPANY,
            project_id=PROJECT,
            user_id=OTHER_USER,
        )
        run = await h.runs.create_run(
            thread_id=thread.id,
            company_id=COMPANY,
            project_id=PROJECT,
            user_id=OTHER_USER,
            business_mode=RunBusinessMode.QA,
        )
        return run.id

    import asyncio

    run_id = asyncio.run(seed())

    with TestClient(h.app) as client:
        response = client.get(f"/api/v1/runs/{run_id}", headers=h.headers())

    assert response.status_code == 403
