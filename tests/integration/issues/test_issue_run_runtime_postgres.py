from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from tests.helpers.jwt import make_hs256_token

from project_agent.config import Settings
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.runs import AgentEventType, RunStatus
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    BackgroundJobModel,
    ClientModel,
    DocumentModel,
    DocumentVersionModel,
    IdempotencyRecordModel,
    IssueDraftModel,
    ProjectKnowledgeSpaceModel,
    ProjectMembershipModel,
    ProjectModel,
    SandboxIssueModel,
    SandboxProjectModel,
    ThreadModel,
    ToolConfirmationModel,
)
from project_agent.infrastructure.db.repositories.runs import SqlAlchemyRunRepository
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run WS5 live issue runtime acceptance",
)

SECRET = "ws5-live-issue-runtime-secret-value-123456"
QUERY = "模块: import ERR-IMPORT-004 failed during acceptance"


@dataclass(frozen=True, slots=True)
class SeededScope:
    company_id: UUID
    client_id: UUID
    project_id: UUID
    user_id: UUID
    sandbox_project_id: UUID
    existing_issue_id: UUID
    project_code: str
    knowledge_space_id: str
    requirement_version_id: UUID | None


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
        retention_sweep_enabled=False,
    )


def _token(settings: Settings, user_id: UUID) -> str:
    return make_hs256_token(
        user_id=user_id,
        secret=SECRET,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_scope(
    factory,
    *,
    include_requirement: bool,
) -> SeededScope:  # type: ignore[no-untyped-def]
    company_id = uuid4()
    client_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    sandbox_project_id = uuid4()
    existing_issue_id = uuid4()
    project_code = f"WS5-{project_id.hex[:10]}"
    knowledge_space_id = f"ws5-space-{project_id.hex[:12]}"
    requirement_version_id = uuid4() if include_requirement else None
    now = datetime.now(UTC)

    async with factory() as session:
        session.add(
            ClientModel(
                id=client_id,
                company_id=company_id,
                name=f"WS5 Live Client {client_id}",
            )
        )
        await session.flush()
        session.add(
            ProjectModel(
                id=project_id,
                company_id=company_id,
                client_id=client_id,
                code=project_code,
                name="WS5 Live Issue Runtime",
                phase="acceptance",
                manager_id=user_id,
                lifecycle_status="ACTIVE",
            )
        )
        await session.flush()
        session.add(
            ProjectMembershipModel(
                project_id=project_id,
                user_id=user_id,
                role="developer",
                valid_from=now - timedelta(minutes=5),
                valid_to=None,
            )
        )
        session.add(
            ProjectKnowledgeSpaceModel(
                project_id=project_id,
                provider="ragflow",
                external_space_id=knowledge_space_id,
                status="active",
            )
        )
        session.add(
            SandboxProjectModel(
                id=sandbox_project_id,
                project_id=project_id,
                external_key=f"WS5-{project_id.hex[:8]}",
                name="WS5 Issue Sandbox",
            )
        )
        await session.flush()
        session.add(
            SandboxIssueModel(
                id=existing_issue_id,
                project_id=project_id,
                sandbox_project_id=sandbox_project_id,
                issue_key=f"EXIST-{existing_issue_id.hex[:8]}",
                title="Existing import failure",
                description="ERR-IMPORT-004 already observed",
                issue_type="bug",
                priority="medium",
                status="OPEN",
                module="import",
                error_code="ERR-IMPORT-004",
                reporter_id=user_id,
            )
        )
        if requirement_version_id is not None:
            document_id = uuid4()
            session.add(
                DocumentModel(
                    id=document_id,
                    company_id=company_id,
                    project_id=project_id,
                    document_category=DocumentCategory.REQUIREMENT_BASELINE.value,
                    title="WS5 import acceptance requirement",
                    owner_user_id=user_id,
                )
            )
            await session.flush()
            session.add(
                DocumentVersionModel(
                    id=requirement_version_id,
                    document_id=document_id,
                    version_no=1,
                    version_label="v1",
                    authority_level=AuthorityLevel.REQUIREMENT_BASELINE.value,
                    lifecycle_status=DocumentLifecycleStatus.PUBLISHED.value,
                    effective_from=date(2026, 1, 1),
                    effective_to=None,
                    content_hash=f"ws5-{requirement_version_id.hex}",
                    published_at=now,
                    created_by=user_id,
                )
            )
        await session.commit()

    return SeededScope(
        company_id=company_id,
        client_id=client_id,
        project_id=project_id,
        user_id=user_id,
        sandbox_project_id=sandbox_project_id,
        existing_issue_id=existing_issue_id,
        project_code=project_code,
        knowledge_space_id=knowledge_space_id,
        requirement_version_id=requirement_version_id,
    )


async def _load_run_events(factory, run_id: UUID):  # type: ignore[no-untyped-def]
    async with factory() as session:
        repo = SqlAlchemyRunRepository(session)
        run = await repo.get_run(run_id)
        events = (
            await session.scalars(
                select(AgentEventModel)
                .where(AgentEventModel.run_id == run_id)
                .order_by(AgentEventModel.sequence_no)
            )
        ).all()
        return run, events


async def _issue_side_effect_counts(
    factory,
    scope: SeededScope,
    run_id: UUID,
) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    async with factory() as session:
        drafts = await session.scalar(
            select(func.count())
            .select_from(IssueDraftModel)
            .where(IssueDraftModel.run_id == run_id)
        )
        confirmations = await session.scalar(
            select(func.count())
            .select_from(ToolConfirmationModel)
            .where(ToolConfirmationModel.run_id == run_id)
        )
        issues = await session.scalar(
            select(func.count())
            .select_from(SandboxIssueModel)
            .where(SandboxIssueModel.project_id == scope.project_id)
        )
        return int(drafts or 0), int(confirmations or 0), int(issues or 0)


async def _cleanup(database_url: str, scope: SeededScope) -> None:
    from project_agent.agent.checkpoint import async_postgres_saver

    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            thread_ids = tuple(
                (
                    await session.scalars(
                        select(ThreadModel.id).where(ThreadModel.project_id == scope.project_id)
                    )
                ).all()
            )
            run_ids = tuple(
                (
                    await session.scalars(
                        select(AgentRunModel.id).where(AgentRunModel.project_id == scope.project_id)
                    )
                ).all()
            )
        if thread_ids:
            async with async_postgres_saver(database_url) as saver:
                for thread_id in thread_ids:
                    await saver.adelete_thread(str(thread_id))
        async with factory() as session:
            if run_ids:
                await session.execute(
                    delete(BackgroundJobModel).where(
                        BackgroundJobModel.aggregate_id.in_(tuple(str(value) for value in run_ids))
                    )
                )
            await session.execute(delete(ProjectModel).where(ProjectModel.id == scope.project_id))
            await session.execute(delete(ClientModel).where(ClientModel.id == scope.client_id))
            await session.commit()
    finally:
        await engine.dispose()


def _create_run(settings: Settings, scope: SeededScope, *, mode: str) -> tuple[UUID, UUID]:
    token = _token(settings, scope.user_id)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/runs",
            json={
                "project_id": str(scope.project_id),
                "business_mode": mode,
                "query": QUERY,
            },
            headers=_headers(token),
        )
    assert response.status_code == 201, response.text
    body = response.json()
    return UUID(body["run_id"]), UUID(body["thread_id"])


def _resume_run(
    settings: Settings,
    scope: SeededScope,
    run_id: UUID,
    *,
    request_payload_hash: str,
) -> None:
    token = _token(settings, scope.user_id)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={
                "action": "confirm",
                "request_payload_hash": request_payload_hash,
            },
            headers=_headers(token),
        )
    assert response.status_code == 202, response.text


@pytest.mark.asyncio
async def test_live_issue_lookup_run_is_authorized_and_read_only(tmp_path: Path) -> None:
    pytest.importorskip("langgraph", reason="LangGraph is required for WS5 live acceptance")
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    scope = await _seed_scope(factory, include_requirement=True)
    settings = _settings(tmp_path, database_url)

    from tests.fakes.knowledge import FakeKnowledgePort

    from project_agent.runtime.issue import build_issue_graph_executor_factory
    from project_agent.runtime.worker import build_worker_runtime

    try:
        run_id, _thread_id = _create_run(settings, scope, mode="issue_lookup")
        before = await _issue_side_effect_counts(factory, scope, run_id)

        async with build_worker_runtime(
            settings,
            graph_executor_factory=build_issue_graph_executor_factory(
                settings, knowledge=FakeKnowledgePort()
            ),
        ) as runtime:
            assert await runtime.worker.run_once() == 1

        run, events = await _load_run_events(factory, run_id)
        after = await _issue_side_effect_counts(factory, scope, run_id)

        assert run is not None
        assert run.status is RunStatus.SUCCEEDED
        assert run.result_ref is not None
        lifecycle = [
            event.event_type
            for event in events
            if event.event_type
            in {
                AgentEventType.RUN_QUEUED.value,
                AgentEventType.RUN_STARTED.value,
                AgentEventType.RUN_SUCCEEDED.value,
            }
        ]
        assert lifecycle == [
            AgentEventType.RUN_QUEUED.value,
            AgentEventType.RUN_STARTED.value,
            AgentEventType.RUN_SUCCEEDED.value,
        ]
        candidate_events = [
            event
            for event in events
            if (
                event.event_type == AgentEventType.ARTIFACT_AVAILABLE.value
                and event.payload_json.get("artifact_type") == "ISSUE_CANDIDATES"
            )
        ]
        assert len(candidate_events) == 1
        candidate_event = candidate_events[0]
        assert run.result_ref == str(candidate_event.id)
        artifact = candidate_event.payload_json["artifact"]
        candidates = artifact["possible_duplicates"]
        assert candidates
        assert candidates[0]["issue_key"] == f"EXIST-{scope.existing_issue_id.hex[:8]}"
        assert before == (0, 0, 1)
        assert after == before
    finally:
        await _cleanup(database_url, scope)
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_issue_create_without_requirement_or_test_evidence_refuses_before_draft(
    tmp_path: Path,
) -> None:
    pytest.importorskip("langgraph", reason="LangGraph is required for WS5 live acceptance")
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    scope = await _seed_scope(factory, include_requirement=False)
    settings = _settings(tmp_path, database_url)

    from tests.fakes.knowledge import FakeKnowledgePort

    from project_agent.runtime.issue import build_issue_graph_executor_factory
    from project_agent.runtime.worker import build_worker_runtime

    try:
        run_id, _thread_id = _create_run(settings, scope, mode="issue_create")

        async with build_worker_runtime(
            settings,
            graph_executor_factory=build_issue_graph_executor_factory(
                settings, knowledge=FakeKnowledgePort()
            ),
        ) as runtime:
            assert await runtime.worker.run_once() == 1

        run, events = await _load_run_events(factory, run_id)
        side_effects = await _issue_side_effect_counts(factory, scope, run_id)

        assert run is not None
        assert run.status is RunStatus.REFUSED
        refused = [
            event for event in events if event.event_type == AgentEventType.RUN_REFUSED.value
        ]
        assert len(refused) == 1
        assert refused[0].payload_json["summary"] == "EVIDENCE_REQUIRED"
        assert side_effects == (0, 0, 1)
    finally:
        await _cleanup(database_url, scope)
        await engine.dispose()


@pytest.mark.asyncio
async def test_live_issue_create_interrupt_restart_resume_creates_exactly_one_issue(
    tmp_path: Path,
) -> None:
    pytest.importorskip("langgraph", reason="LangGraph is required for WS5 live acceptance")
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    scope = await _seed_scope(factory, include_requirement=True)
    assert scope.requirement_version_id is not None
    settings = _settings(tmp_path, database_url)

    from tests.fakes.knowledge import FakeKnowledgePort

    from project_agent.runtime.issue import build_issue_graph_executor_factory
    from project_agent.runtime.worker import build_worker_runtime

    knowledge = FakeKnowledgePort()
    knowledge.add_chunk(
        project_id=scope.project_code,
        document_version_id=str(scope.requirement_version_id),
        content="ERR-IMPORT-004 acceptance failures must create a tracked issue.",
        score=0.99,
        knowledge_space_id=scope.knowledge_space_id,
        provider_ref="ws5-live-requirement",
    )

    try:
        run_id, _thread_id = _create_run(settings, scope, mode="issue_create")

        async with build_worker_runtime(
            settings,
            graph_executor_factory=build_issue_graph_executor_factory(
                settings, knowledge=knowledge
            ),
        ) as first_runtime:
            assert await first_runtime.worker.run_once() == 1

        run, events = await _load_run_events(factory, run_id)
        assert run is not None
        assert run.status is RunStatus.WAITING_CONFIRMATION
        waiting = [
            event
            for event in events
            if event.event_type == AgentEventType.WAITING_CONFIRMATION.value
        ]
        assert len(waiting) == 1
        waiting_payload = waiting[0].payload_json
        assert waiting_payload["request_payload_hash"]
        assert waiting_payload["possible_duplicates"]
        assert waiting_payload["evidence_ids"]

        async with factory() as session:
            draft = (
                await session.scalars(
                    select(IssueDraftModel).where(IssueDraftModel.run_id == run_id)
                )
            ).one()
            confirmations_before = await session.scalar(
                select(func.count())
                .select_from(ToolConfirmationModel)
                .where(ToolConfirmationModel.run_id == run_id)
            )
        assert tuple(waiting_payload["evidence_ids"]) == tuple(draft.evidence_ids_json)
        assert int(confirmations_before or 0) == 0

        _resume_run(
            settings,
            scope,
            run_id,
            request_payload_hash=str(waiting_payload["request_payload_hash"]),
        )

        async with build_worker_runtime(
            settings,
            graph_executor_factory=build_issue_graph_executor_factory(
                settings, knowledge=knowledge
            ),
        ) as second_runtime:
            assert await second_runtime.worker.run_once() == 1

        final_run, final_events = await _load_run_events(factory, run_id)
        assert final_run is not None
        assert final_run.status is RunStatus.SUCCEEDED
        event_types = [event.event_type for event in final_events]
        assert event_types.count(AgentEventType.RUN_RESUMED.value) == 1
        assert event_types.count(AgentEventType.RUN_SUCCEEDED.value) == 1

        async with factory() as session:
            created_issues = (
                await session.scalars(
                    select(SandboxIssueModel).where(
                        SandboxIssueModel.project_id == scope.project_id,
                        SandboxIssueModel.client_request_id == str(draft.id),
                    )
                )
            ).all()
            records = (
                await session.scalars(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.namespace == "sandbox_issue_create",
                        IdempotencyRecordModel.request_id == str(draft.id),
                    )
                )
            ).all()
            confirmations_after = await session.scalar(
                select(func.count())
                .select_from(ToolConfirmationModel)
                .where(ToolConfirmationModel.run_id == run_id)
            )
        assert len(created_issues) == 1
        assert len(records) == 1
        assert records[0].status == "COMPLETED"
        assert int(confirmations_after or 0) == 1
    finally:
        await _cleanup(database_url, scope)
        await engine.dispose()
