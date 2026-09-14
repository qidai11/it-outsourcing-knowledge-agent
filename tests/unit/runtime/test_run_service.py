from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.ports.job_queue import EnqueueJobRequest
from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunStatus
from project_agent.infrastructure.jobs.postgres import SqlAlchemySessionJobEnqueuer
from tests.fakes.run_repository import FakeRunRepository


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_calls = 0
        self.refresh_calls = 0
        self.commit_calls = 0

    def add(self, row: object) -> None:
        self.added.append(row)
        if getattr(row, "id", None) is None:
            setattr(row, "id", uuid4())

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
