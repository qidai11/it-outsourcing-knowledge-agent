from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.jwt import make_hs256_token

from project_agent.api.dependencies import get_authorization_service, get_db_session
from project_agent.api.v1.runs import RunApiServices, get_run_api_services
from project_agent.application.ports.job_queue import EnqueueJobRequest, QueuedJob
from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.runs import RunApplicationService
from project_agent.config import Settings
from project_agent.domain.runs import AgentEventType, RunJobType, RunStatus
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    BackgroundJobModel,
    ClientModel,
    ProjectMembershipModel,
    ProjectModel,
    ThreadModel,
)
from project_agent.infrastructure.db.repositories.runs import SqlAlchemyRunRepository
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL Run API integration",
)

SECRET = "ws2-postgres-run-api-secret-value-123456"


class FailingJobEnqueuer:
    async def enqueue(self, request: EnqueueJobRequest) -> QueuedJob:
        del request
        raise RuntimeError("forced enqueue failure")


class SeededScope:
    def __init__(self) -> None:
        self.company_id = uuid4()
        self.client_id = uuid4()
        self.project_a = uuid4()
        self.project_b = uuid4()
        self.user_a = uuid4()
        self.user_b = uuid4()


async def _seed_scope(session: AsyncSession, scope: SeededScope) -> None:
    now = datetime.now(UTC)
    session.add(
        ClientModel(
            id=scope.client_id,
            company_id=scope.company_id,
            name=f"WS2 client {scope.client_id}",
            status="active",
        )
    )
    await session.flush()
    session.add_all(
        [
            ProjectModel(
                id=scope.project_a,
                company_id=scope.company_id,
                client_id=scope.client_id,
                code=f"WS2A-{scope.project_a.hex[:10]}",
                name="WS2 project A",
                manager_id=scope.user_a,
                lifecycle_status="ACTIVE",
            ),
            ProjectModel(
                id=scope.project_b,
                company_id=scope.company_id,
                client_id=scope.client_id,
                code=f"WS2B-{scope.project_b.hex[:10]}",
                name="WS2 project B",
                manager_id=scope.user_b,
                lifecycle_status="ACTIVE",
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            ProjectMembershipModel(
                project_id=scope.project_a,
                user_id=scope.user_a,
                role="developer",
                valid_from=now - timedelta(minutes=5),
                valid_to=None,
            ),
            ProjectMembershipModel(
                project_id=scope.project_b,
                user_id=scope.user_b,
                role="developer",
                valid_from=now - timedelta(minutes=5),
                valid_to=None,
            ),
        ]
    )
    await session.commit()


async def _cleanup_scope(session: AsyncSession, scope: SeededScope) -> None:
    run_ids = tuple(
        (
            await session.scalars(
                select(AgentRunModel.id).where(
                    AgentRunModel.project_id.in_((scope.project_a, scope.project_b))
                )
            )
        ).all()
    )
    if run_ids:
        await session.execute(
            delete(BackgroundJobModel).where(
                BackgroundJobModel.aggregate_id.in_(tuple(str(run_id) for run_id in run_ids))
            )
        )
    await session.execute(
        delete(ProjectModel).where(ProjectModel.id.in_((scope.project_a, scope.project_b)))
    )
    await session.execute(delete(ClientModel).where(ClientModel.id == scope.client_id))
    await session.commit()


def _settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
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


def _token(
    *,
    settings: Settings,
    user_id: UUID,
    extra_claims: dict[str, object] | None = None,
) -> str:
    return make_hs256_token(
        user_id=user_id,
        secret=SECRET,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        extra_claims=extra_claims,
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _run_payload(*, project_id: UUID, business_mode: str = "qa") -> dict[str, str]:
    return {
        "project_id": str(project_id),
        "business_mode": business_mode,
        "query": "What changed in the approved scope?",
    }


def _sse_ids(body: str) -> list[int]:
    return [int(line.removeprefix("id: ")) for line in body.splitlines() if line.startswith("id: ")]


@pytest.mark.asyncio
async def test_live_create_atomically_persists_run_event_and_execute_job(tmp_path: Path) -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    scope = SeededScope()
    async with sessions() as session:
        await _seed_scope(session, scope)
    settings = _settings(tmp_path, database_url)
    token = _token(settings=settings, user_id=scope.user_a)

    try:
        with TestClient(create_app(settings)) as client:
            response = client.post(
                "/api/v1/runs",
                json=_run_payload(project_id=scope.project_a),
                headers=_headers(token),
            )
        assert response.status_code == 201
        body = response.json()
        run_id = UUID(body["run_id"])
        thread_id = UUID(body["thread_id"])

        async with sessions() as session:
            thread = await session.get(ThreadModel, thread_id)
            run = await session.get(AgentRunModel, run_id)
            events = (
                await session.scalars(
                    select(AgentEventModel)
                    .where(AgentEventModel.run_id == run_id)
                    .order_by(AgentEventModel.sequence_no)
                )
            ).all()
            jobs = (
                await session.scalars(
                    select(BackgroundJobModel).where(
                        BackgroundJobModel.aggregate_id == str(run_id)
                    )
                )
            ).all()

        assert thread is not None
        assert thread.project_id == scope.project_a
        assert thread.company_id == scope.company_id
        assert thread.user_id == scope.user_a
        assert run is not None
        assert run.project_id == scope.project_a
        assert run.company_id == scope.company_id
        assert run.user_id == scope.user_a
        assert run.business_mode == "qa"
        assert run.status == RunStatus.QUEUED.value
        assert run.started_at is None
        assert [(event.sequence_no, event.event_type) for event in events] == [
            (1, AgentEventType.RUN_QUEUED.value)
        ]
        assert events[0].payload_json["query_text"] == "What changed in the approved scope?"
        assert len(jobs) == 1
        assert jobs[0].job_type == RunJobType.EXECUTE.value
        assert jobs[0].aggregate_id == str(run_id)
        assert "query_text" not in BackgroundJobModel.__table__.columns
        assert "request_payload_hash" not in BackgroundJobModel.__table__.columns
    finally:
        async with sessions() as session:
            await _cleanup_scope(session, scope)
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_enqueue_failure_rolls_back_thread_run_event_and_job(tmp_path: Path) -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    scope = SeededScope()
    async with sessions() as session:
        await _seed_scope(session, scope)
        jobs_before = await session.scalar(select(func.count(BackgroundJobModel.id)))
    settings = _settings(tmp_path, database_url)
    token = _token(settings=settings, user_id=scope.user_a)
    app = create_app(settings)

    async def failing_run_api_services(
        session: Annotated[AsyncSession, Depends(get_db_session)],
        authorization: Annotated[AuthorizationService, Depends(get_authorization_service)],
    ) -> RunApiServices:
        repository = SqlAlchemyRunRepository(session)
        return RunApiServices(
            runs=RunApplicationService(
                authorization=authorization,
                repository=repository,
                jobs=FailingJobEnqueuer(),
            ),
            repository=repository,
        )

    app.dependency_overrides[get_run_api_services] = failing_run_api_services
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/v1/runs",
                json=_run_payload(project_id=scope.project_a),
                headers=_headers(token),
            )
        assert response.status_code == 500

        async with sessions() as session:
            thread_count = await session.scalar(
                select(func.count(ThreadModel.id)).where(ThreadModel.project_id == scope.project_a)
            )
            run_count = await session.scalar(
                select(func.count(AgentRunModel.id)).where(
                    AgentRunModel.project_id == scope.project_a
                )
            )
            event_count = await session.scalar(
                select(func.count(AgentEventModel.id)).join(
                    AgentRunModel,
                    AgentRunModel.id == AgentEventModel.run_id,
                ).where(AgentRunModel.project_id == scope.project_a)
            )
            jobs_after = await session.scalar(select(func.count(BackgroundJobModel.id)))
        assert thread_count == 0
        assert run_count == 0
        assert event_count == 0
        assert jobs_after == jobs_before
    finally:
        app.dependency_overrides.clear()
        async with sessions() as session:
            await _cleanup_scope(session, scope)
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_current_membership_revocation_and_cross_project_security(
    tmp_path: Path,
) -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    scope = SeededScope()
    async with sessions() as session:
        await _seed_scope(session, scope)
    settings = _settings(tmp_path, database_url)
    token_a = _token(settings=settings, user_id=scope.user_a)
    token_b = _token(settings=settings, user_id=scope.user_b)
    forged_token_b = _token(
        settings=settings,
        user_id=scope.user_b,
        extra_claims={
            "role": "project_manager",
            "project_ids": [str(scope.project_a)],
        },
    )

    try:
        with TestClient(create_app(settings)) as client:
            created = client.post(
                "/api/v1/runs",
                json=_run_payload(project_id=scope.project_a),
                headers=_headers(token_a),
            )
            assert created.status_code == 201
            run_id = UUID(created.json()["run_id"])

            async with sessions() as session:
                membership = (
                    await session.scalars(
                        select(ProjectMembershipModel).where(
                            ProjectMembershipModel.project_id == scope.project_a,
                            ProjectMembershipModel.user_id == scope.user_a,
                        )
                    )
                ).one()
                membership.valid_to = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()

            revoked = client.get(f"/api/v1/runs/{run_id}", headers=_headers(token_a))
            cross_project = client.get(f"/api/v1/runs/{run_id}", headers=_headers(token_b))
            forged = client.get(
                f"/api/v1/runs/{run_id}",
                headers=_headers(forged_token_b),
            )
            event_stream = client.get(
                f"/api/v1/runs/{run_id}/events",
                headers=_headers(token_b),
            )

        assert revoked.status_code == 403
        assert cross_project.status_code == 403
        assert forged.status_code == 403
        assert event_stream.status_code == 403
    finally:
        async with sessions() as session:
            await _cleanup_scope(session, scope)
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_resume_is_durable_atomic_and_replay_safe(tmp_path: Path) -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    scope = SeededScope()
    async with sessions() as session:
        await _seed_scope(session, scope)
    settings = _settings(tmp_path, database_url)
    token = _token(settings=settings, user_id=scope.user_a)
    request_hash = "a" * 64

    try:
        with TestClient(create_app(settings)) as client:
            created = client.post(
                "/api/v1/runs",
                json=_run_payload(project_id=scope.project_a, business_mode="issue_create"),
                headers=_headers(token),
            )
            assert created.status_code == 201
            run_id = UUID(created.json()["run_id"])

            async with sessions() as session:
                run = await session.get(AgentRunModel, run_id)
                assert run is not None
                run.status = RunStatus.WAITING_CONFIRMATION.value
                session.add(
                    AgentEventModel(
                        run_id=run_id,
                        sequence_no=2,
                        event_type=AgentEventType.WAITING_CONFIRMATION.value,
                        payload_json={"request_payload_hash": request_hash},
                    )
                )
                await session.commit()

            resume_payload = {
                "action": "confirm",
                "request_payload_hash": request_hash,
            }
            first = client.post(
                f"/api/v1/runs/{run_id}/resume",
                json=resume_payload,
                headers=_headers(token),
            )
            second = client.post(
                f"/api/v1/runs/{run_id}/resume",
                json=resume_payload,
                headers=_headers(token),
            )

        assert first.status_code == 202
        assert second.status_code == 409
        async with sessions() as session:
            run = await session.get(AgentRunModel, run_id)
            resume_events = (
                await session.scalars(
                    select(AgentEventModel).where(
                        AgentEventModel.run_id == run_id,
                        AgentEventModel.event_type == AgentEventType.RUN_RESUME_QUEUED.value,
                    )
                )
            ).all()
            resume_jobs = (
                await session.scalars(
                    select(BackgroundJobModel).where(
                        BackgroundJobModel.aggregate_id == str(run_id),
                        BackgroundJobModel.job_type == RunJobType.RESUME.value,
                    )
                )
            ).all()

        assert run is not None
        assert run.status == RunStatus.QUEUED.value
        assert len(resume_events) == 1
        assert resume_events[0].payload_json == {
            "action": "confirm",
            "request_payload_hash": request_hash,
            "actor_id": str(scope.user_a),
        }
        assert len(resume_jobs) == 1
    finally:
        async with sessions() as session:
            await _cleanup_scope(session, scope)
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_sse_orders_persisted_events_and_replays_after_cursor(tmp_path: Path) -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    scope = SeededScope()
    async with sessions() as session:
        await _seed_scope(session, scope)
    settings = _settings(tmp_path, database_url)
    token = _token(settings=settings, user_id=scope.user_a)

    try:
        with TestClient(create_app(settings)) as client:
            created = client.post(
                "/api/v1/runs",
                json=_run_payload(project_id=scope.project_a),
                headers=_headers(token),
            )
            assert created.status_code == 201
            run_id = UUID(created.json()["run_id"])

            async with sessions() as session:
                run = await session.get(AgentRunModel, run_id)
                assert run is not None
                session.add_all(
                    [
                        AgentEventModel(
                            run_id=run_id,
                            sequence_no=2,
                            event_type=AgentEventType.RUN_PROGRESS.value,
                            payload_json={"message": "working"},
                        ),
                        AgentEventModel(
                            run_id=run_id,
                            sequence_no=3,
                            event_type=AgentEventType.RUN_SUCCEEDED.value,
                            payload_json={"summary": "done"},
                        ),
                    ]
                )
                run.status = RunStatus.SUCCEEDED.value
                run.finished_at = datetime.now(UTC)
                await session.commit()

            with client.stream(
                "GET",
                f"/api/v1/runs/{run_id}/events",
                headers=_headers(token),
            ) as response:
                assert response.status_code == 200
                first_body = "".join(response.iter_text())

            reconnect_headers = _headers(token) | {"Last-Event-ID": "1"}
            with client.stream(
                "GET",
                f"/api/v1/runs/{run_id}/events",
                headers=reconnect_headers,
            ) as response:
                assert response.status_code == 200
                replay_body = "".join(response.iter_text())

        assert _sse_ids(first_body) == [1, 2, 3]
        assert _sse_ids(replay_body) == [2, 3]
        assert "event: RUN_SUCCEEDED" in first_body
        assert "event: RUN_SUCCEEDED" in replay_body
    finally:
        async with sessions() as session:
            await _cleanup_scope(session, scope)
        await engine.dispose()
