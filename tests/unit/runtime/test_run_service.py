from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.job_queue import FakeJobQueue
from tests.fakes.run_repository import FakeRunRepository

from project_agent.application.ports.job_queue import EnqueueJobRequest
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationDenied,
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.application.services.runs import (
    CreateRunCommand,
    RunAccessDenied,
    RunApplicationService,
    RunNotFound,
    ThreadNotFound,
)
from project_agent.domain.enums import ProjectRole
from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunJobType, RunStatus
from project_agent.infrastructure.jobs.postgres import SqlAlchemySessionJobEnqueuer


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
COMPANY = UUID("11111111-1111-4111-8111-111111111111")
OTHER_COMPANY = UUID("22222222-2222-4222-8222-222222222222")
CLIENT = UUID("33333333-3333-4333-8333-333333333333")
PROJECT = UUID("44444444-4444-4444-8444-444444444444")
OTHER_PROJECT = UUID("55555555-5555-4555-8555-555555555555")
USER = UUID("66666666-6666-4666-8666-666666666666")
OTHER_USER = UUID("77777777-7777-4777-8777-777777777777")


def membership(
    *,
    project_id: UUID = PROJECT,
    company_id: UUID = COMPANY,
    valid_to: datetime | None = None,
) -> MembershipAccessRecord:
    return MembershipAccessRecord(
        company_id=company_id,
        client_id=CLIENT,
        project_id=project_id,
        project_code="PRJ-TEST",
        role=ProjectRole.DEVELOPER,
        valid_from=NOW - timedelta(days=1),
        valid_to=valid_to,
    )


def run_service_fixture() -> tuple[
    RunApplicationService,
    FakeProjectAuthorizationRepository,
    FakeRunRepository,
    FakeJobQueue,
]:
    auth_repo = FakeProjectAuthorizationRepository()
    runs = FakeRunRepository()
    jobs = FakeJobQueue()
    service = RunApplicationService(
        authorization=AuthorizationService(auth_repo, clock=lambda: NOW),
        repository=runs,
        jobs=jobs,
    )
    return service, auth_repo, runs, jobs


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_calls = 0
        self.refresh_calls = 0
        self.commit_calls = 0

    def add(self, row: object) -> None:
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid4()

    async def flush(self) -> None:
        self.flush_calls += 1

    async def refresh(self, _row: object) -> None:
        self.refresh_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1


@pytest.mark.asyncio
async def test_fake_run_repository_allocates_event_sequences_per_run() -> None:
    repository = FakeRunRepository()
    company_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    thread = await repository.create_thread(
        company_id=company_id,
        project_id=project_id,
        user_id=user_id,
    )
    run = await repository.create_run(
        thread_id=thread.id,
        company_id=company_id,
        project_id=project_id,
        user_id=user_id,
        business_mode=RunBusinessMode.QA,
    )

    first = await repository.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"step": 1},
    )
    second = await repository.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_PROGRESS,
        payload={"step": 2},
    )
    third = await repository.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_PROGRESS,
        payload={"step": 3},
    )

    assert [first.sequence_no, second.sequence_no, third.sequence_no] == [1, 2, 3]
    after_first = await repository.list_events_after(
        run_id=run.id,
        after_sequence=1,
    )
    assert [event.sequence_no for event in after_first] == [2, 3]
    assert run.status is RunStatus.QUEUED
    assert run.started_at is None


@pytest.mark.asyncio
async def test_fake_run_repository_tracks_each_run_sequence_independently() -> None:
    repository = FakeRunRepository()
    company_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    thread = await repository.create_thread(
        company_id=company_id,
        project_id=project_id,
        user_id=user_id,
    )
    left = await repository.create_run(
        thread_id=thread.id,
        company_id=company_id,
        project_id=project_id,
        user_id=user_id,
        business_mode=RunBusinessMode.QA,
    )
    right = await repository.create_run(
        thread_id=thread.id,
        company_id=company_id,
        project_id=project_id,
        user_id=user_id,
        business_mode=RunBusinessMode.ISSUE_LOOKUP,
    )

    left_event = await repository.append_event(
        run_id=left.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={},
    )
    right_event = await repository.append_event(
        run_id=right.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={},
    )

    assert left_event.sequence_no == 1
    assert right_event.sequence_no == 1


@pytest.mark.asyncio
async def test_session_job_enqueuer_flushes_without_committing() -> None:
    session = RecordingSession()
    enqueuer = SqlAlchemySessionJobEnqueuer(cast(AsyncSession, session))

    created = await enqueuer.enqueue(
        EnqueueJobRequest(job_type="EXECUTE_AGENT_RUN", aggregate_id="run-1")
    )

    assert UUID(created.job_id)
    assert created.aggregate_id == "run-1"
    assert session.flush_calls == 1
    assert session.refresh_calls == 1
    assert session.commit_calls == 0
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_create_run_persists_project_bound_thread_event_and_execute_job() -> None:
    service, auth_repo, runs, jobs = run_service_fixture()
    auth_repo.memberships[(USER, PROJECT)] = membership()

    created = await service.create_run(
        identity=AuthenticatedIdentity(user_id=USER),
        command=CreateRunCommand(
            project_id=PROJECT,
            business_mode=RunBusinessMode.QA,
            query_text="  REQ-3.2.1 deployment window?  ",
        ),
    )

    thread = runs.threads[created.thread_id]
    assert created.project_id == PROJECT
    assert created.company_id == COMPANY
    assert created.user_id == USER
    assert created.status is RunStatus.QUEUED
    assert created.business_mode is RunBusinessMode.QA
    assert created.started_at is None
    assert thread.project_id == PROJECT
    assert thread.company_id == COMPANY
    assert thread.user_id == USER
    assert runs.events[created.id][0].event_type is AgentEventType.RUN_QUEUED
    assert runs.events[created.id][0].payload == {
        "query_text": "REQ-3.2.1 deployment window?"
    }
    assert len(jobs.jobs) == 1
    assert jobs.jobs[0].job_type == RunJobType.EXECUTE.value
    assert jobs.jobs[0].aggregate_id == str(created.id)


@pytest.mark.asyncio
async def test_create_run_rejects_blank_query_before_any_side_effect() -> None:
    service, auth_repo, runs, jobs = run_service_fixture()
    auth_repo.memberships[(USER, PROJECT)] = membership()

    with pytest.raises(ValueError, match="query"):
        await service.create_run(
            identity=AuthenticatedIdentity(user_id=USER),
            command=CreateRunCommand(
                project_id=PROJECT,
                business_mode=RunBusinessMode.QA,
                query_text="   ",
            ),
        )

    assert runs.threads == {}
    assert runs.runs == {}
    assert runs.events == {}
    assert jobs.jobs == ()


@pytest.mark.asyncio
async def test_create_run_denies_non_member_without_side_effects() -> None:
    service, _auth_repo, runs, jobs = run_service_fixture()

    with pytest.raises(AuthorizationDenied):
        await service.create_run(
            identity=AuthenticatedIdentity(user_id=USER),
            command=CreateRunCommand(
                project_id=PROJECT,
                business_mode=RunBusinessMode.QA,
                query_text="question",
            ),
        )

    assert runs.threads == {}
    assert runs.runs == {}
    assert jobs.jobs == ()


@pytest.mark.asyncio
async def test_create_run_denies_revoked_membership_without_side_effects() -> None:
    service, auth_repo, runs, jobs = run_service_fixture()
    auth_repo.memberships[(USER, PROJECT)] = membership(valid_to=NOW)

    with pytest.raises(AuthorizationDenied):
        await service.create_run(
            identity=AuthenticatedIdentity(user_id=USER),
            command=CreateRunCommand(
                project_id=PROJECT,
                business_mode=RunBusinessMode.QA,
                query_text="question",
            ),
        )

    assert runs.threads == {}
    assert runs.runs == {}
    assert jobs.jobs == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("thread_project", "thread_company", "thread_user"),
    [
        (OTHER_PROJECT, COMPANY, USER),
        (PROJECT, OTHER_COMPANY, USER),
        (PROJECT, COMPANY, OTHER_USER),
    ],
)
async def test_create_run_rejects_existing_thread_with_wrong_scope(
    thread_project: UUID,
    thread_company: UUID,
    thread_user: UUID,
) -> None:
    service, auth_repo, runs, jobs = run_service_fixture()
    auth_repo.memberships[(USER, PROJECT)] = membership()
    thread = await runs.create_thread(
        company_id=thread_company,
        project_id=thread_project,
        user_id=thread_user,
    )

    with pytest.raises(RunAccessDenied):
        await service.create_run(
            identity=AuthenticatedIdentity(user_id=USER),
            command=CreateRunCommand(
                project_id=PROJECT,
                business_mode=RunBusinessMode.QA,
                query_text="question",
                thread_id=thread.id,
            ),
        )

    assert runs.runs == {}
    assert jobs.jobs == ()


@pytest.mark.asyncio
async def test_create_run_rejects_missing_supplied_thread() -> None:
    service, auth_repo, runs, jobs = run_service_fixture()
    auth_repo.memberships[(USER, PROJECT)] = membership()

    with pytest.raises(ThreadNotFound):
        await service.create_run(
            identity=AuthenticatedIdentity(user_id=USER),
            command=CreateRunCommand(
                project_id=PROJECT,
                business_mode=RunBusinessMode.QA,
                query_text="question",
                thread_id=uuid4(),
            ),
        )

    assert runs.runs == {}
    assert jobs.jobs == ()


@pytest.mark.asyncio
async def test_get_run_reauthorizes_current_membership() -> None:
    service, auth_repo, runs, _jobs = run_service_fixture()
    auth_repo.memberships[(USER, PROJECT)] = membership()
    thread = await runs.create_thread(company_id=COMPANY, project_id=PROJECT, user_id=USER)
    run = await runs.create_run(
        thread_id=thread.id,
        company_id=COMPANY,
        project_id=PROJECT,
        user_id=USER,
        business_mode=RunBusinessMode.QA,
    )

    loaded = await service.get_run(identity=AuthenticatedIdentity(user_id=USER), run_id=run.id)
    assert loaded.id == run.id

    auth_repo.memberships[(USER, PROJECT)] = replace(membership(), valid_to=NOW)
    with pytest.raises(AuthorizationDenied):
        await service.get_run(identity=AuthenticatedIdentity(user_id=USER), run_id=run.id)


@pytest.mark.asyncio
async def test_get_run_missing_id_is_not_found() -> None:
    service, _auth_repo, _runs, _jobs = run_service_fixture()

    with pytest.raises(RunNotFound):
        await service.get_run(identity=AuthenticatedIdentity(user_id=USER), run_id=uuid4())


@pytest.mark.asyncio
async def test_get_run_denies_member_of_another_project() -> None:
    service, auth_repo, runs, _jobs = run_service_fixture()
    auth_repo.memberships[(USER, OTHER_PROJECT)] = membership(project_id=OTHER_PROJECT)
    thread = await runs.create_thread(company_id=COMPANY, project_id=PROJECT, user_id=OTHER_USER)
    run = await runs.create_run(
        thread_id=thread.id,
        company_id=COMPANY,
        project_id=PROJECT,
        user_id=OTHER_USER,
        business_mode=RunBusinessMode.QA,
    )

    with pytest.raises(AuthorizationDenied):
        await service.get_run(identity=AuthenticatedIdentity(user_id=USER), run_id=run.id)
