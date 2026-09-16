from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from project_agent.application.ports.job_queue import EnqueueJobRequest, JobState
from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind
from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunJobType, RunStatus
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    BackgroundJobModel,
    ClientModel,
    ProjectModel,
    ThreadModel,
)
from project_agent.infrastructure.db.repositories.runs import SqlAlchemyRunRepository
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.jobs.postgres import (
    PostgresJobQueue,
    SqlAlchemySessionJobEnqueuer,
)
from project_agent.workers.handlers import EXECUTE_AGENT_RUN, HandlerRegistry
from project_agent.workers.main import BackgroundWorker, WorkerSettings
from project_agent.workers.run_execution import ExecuteAgentRunHandler

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL Worker gate",
)


@dataclass(frozen=True, slots=True)
class SeededRun:
    client_id: UUID
    project_id: UUID
    thread_id: UUID
    run_id: UUID
    job_id: str


class ScriptedGraphExecutor:
    def __init__(self, steps: Sequence[RunGraphOutcome | Exception]) -> None:
        self._steps = list(steps)
        self.execute_calls = 0

    async def execute(self, run):  # type: ignore[no-untyped-def]
        del run
        self.execute_calls += 1
        if not self._steps:
            raise AssertionError("unexpected graph execute call")
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    async def resume(self, run, resume_payload):  # type: ignore[no-untyped-def]
        del run, resume_payload
        raise AssertionError("resume is not expected in EXECUTE_AGENT_RUN tests")


async def _seed_execute_run(
    factory,
    *,
    max_attempts: int = 3,
) -> SeededRun:  # type: ignore[no-untyped-def]
    company_id = uuid4()
    user_id = uuid4()
    manager_id = uuid4()
    client_id = uuid4()
    project_id = uuid4()
    thread_id = uuid4()
    run_id = uuid4()

    async with factory() as session:
        session.add(
            ClientModel(
                id=client_id,
                company_id=company_id,
                name=f"WS3 Worker Client {client_id}",
            )
        )
        await session.flush()

        session.add(
            ProjectModel(
                id=project_id,
                company_id=company_id,
                client_id=client_id,
                code=f"ws3-{project_id.hex[:12]}",
                name="WS3 Worker Integration",
                manager_id=manager_id,
            )
        )
        await session.flush()

        session.add(
            ThreadModel(
                id=thread_id,
                company_id=company_id,
                project_id=project_id,
                user_id=user_id,
            )
        )
        await session.flush()

        session.add(
            AgentRunModel(
                id=run_id,
                thread_id=thread_id,
                company_id=company_id,
                project_id=project_id,
                user_id=user_id,
                business_mode=RunBusinessMode.QA.value,
                status=RunStatus.QUEUED.value,
                started_at=None,
                finished_at=None,
            )
        )
        await session.flush()

        repo = SqlAlchemyRunRepository(session)
        await repo.append_event(
            run_id=run_id,
            event_type=AgentEventType.RUN_QUEUED,
            payload={"query_text": "prove live worker durability"},
        )
        jobs = SqlAlchemySessionJobEnqueuer(session)
        queued = await jobs.enqueue(
            EnqueueJobRequest(
                job_type=RunJobType.EXECUTE.value,
                aggregate_id=str(run_id),
                max_attempts=max_attempts,
            )
        )
        await session.commit()

    return SeededRun(
        client_id=client_id,
        project_id=project_id,
        thread_id=thread_id,
        run_id=run_id,
        job_id=queued.job_id,
    )


async def _cleanup(factory, seeded: SeededRun) -> None:  # type: ignore[no-untyped-def]
    async with factory() as session:
        await session.execute(
            delete(BackgroundJobModel).where(BackgroundJobModel.id == UUID(seeded.job_id))
        )
        await session.execute(
            delete(AgentEventModel).where(AgentEventModel.run_id == seeded.run_id)
        )
        await session.execute(delete(AgentRunModel).where(AgentRunModel.id == seeded.run_id))
        await session.execute(delete(ThreadModel).where(ThreadModel.id == seeded.thread_id))
        await session.execute(delete(ProjectModel).where(ProjectModel.id == seeded.project_id))
        await session.execute(delete(ClientModel).where(ClientModel.id == seeded.client_id))
        await session.commit()


async def _load_run_and_events(factory, run_id: UUID):  # type: ignore[no-untyped-def]
    async with factory() as session:
        repo = SqlAlchemyRunRepository(session)
        run = await repo.get_run(run_id)
        events = await repo.list_events_after(run_id=run_id, after_sequence=0, limit=100)
        return run, events


def _worker(
    queue: PostgresJobQueue,
    factory,  # type: ignore[no-untyped-def]
    graph: ScriptedGraphExecutor,
) -> BackgroundWorker:
    handlers = HandlerRegistry()
    handlers.register(EXECUTE_AGENT_RUN, ExecuteAgentRunHandler(factory, graph))
    return BackgroundWorker(
        queue,
        handlers,
        worker_id=f"ws3-live-{uuid4()}",
        settings=WorkerSettings(
            concurrency=1,
            claim_limit=1,
            heartbeat_seconds=60,
            poll_seconds=0.01,
        ),
    )


@pytest.mark.asyncio
async def test_execute_agent_run_succeeds_with_durable_run_and_events() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    factory = create_session_factory(engine)
    queue = PostgresJobQueue(factory, retry_base_seconds=0, retry_max_seconds=0)
    seeded = await _seed_execute_run(factory)
    graph = ScriptedGraphExecutor(
        [RunGraphOutcome(kind=RunGraphOutcomeKind.SUCCEEDED, result_ref="answer:live")]
    )

    try:
        assert await _worker(queue, factory, graph).run_once() == 1

        job = await queue.get(seeded.job_id)
        run, events = await _load_run_and_events(factory, seeded.run_id)

        assert job is not None
        assert job.state is JobState.SUCCEEDED
        assert run is not None
        assert run.status is RunStatus.SUCCEEDED
        assert run.started_at is not None
        assert run.finished_at is not None
        assert graph.execute_calls == 1

        event_types = [event.event_type for event in events]
        assert event_types == [
            AgentEventType.RUN_QUEUED,
            AgentEventType.RUN_STARTED,
            AgentEventType.RUN_SUCCEEDED,
        ]
    finally:
        await _cleanup(factory, seeded)
        await engine.dispose()


@pytest.mark.asyncio
async def test_execute_agent_run_retries_without_duplicate_run_started() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    factory = create_session_factory(engine)
    queue = PostgresJobQueue(factory, retry_base_seconds=0, retry_max_seconds=0)
    seeded = await _seed_execute_run(factory, max_attempts=3)
    graph = ScriptedGraphExecutor(
        [
            TimeoutError("transient graph timeout"),
            RunGraphOutcome(kind=RunGraphOutcomeKind.SUCCEEDED),
        ]
    )
    worker = _worker(queue, factory, graph)

    try:
        assert await worker.run_once() == 1
        first_job = await queue.get(seeded.job_id)
        first_run, first_events = await _load_run_and_events(factory, seeded.run_id)

        assert first_job is not None
        assert first_job.state is JobState.PENDING
        assert first_run is not None
        assert first_run.status is RunStatus.RUNNING
        assert [event.event_type for event in first_events].count(AgentEventType.RUN_STARTED) == 1
        assert [event.event_type for event in first_events].count(AgentEventType.RUN_FAILED) == 0

        assert await worker.run_once() == 1
        final_job = await queue.get(seeded.job_id)
        final_run, final_events = await _load_run_and_events(factory, seeded.run_id)

        assert final_job is not None
        assert final_job.state is JobState.SUCCEEDED
        assert final_job.attempts == 2
        assert final_run is not None
        assert final_run.status is RunStatus.SUCCEEDED
        event_types = [event.event_type for event in final_events]
        assert event_types.count(AgentEventType.RUN_STARTED) == 1
        assert event_types.count(AgentEventType.RUN_SUCCEEDED) == 1
        assert event_types.count(AgentEventType.RUN_FAILED) == 0
        assert graph.execute_calls == 2
    finally:
        await _cleanup(factory, seeded)
        await engine.dispose()


@pytest.mark.asyncio
async def test_execute_agent_run_final_failure_projects_once() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    factory = create_session_factory(engine)
    queue = PostgresJobQueue(factory, retry_base_seconds=0, retry_max_seconds=0)
    seeded = await _seed_execute_run(factory, max_attempts=2)
    graph = ScriptedGraphExecutor(
        [
            TimeoutError("first timeout"),
            TimeoutError("final timeout"),
        ]
    )
    worker = _worker(queue, factory, graph)

    try:
        assert await worker.run_once() == 1
        assert await worker.run_once() == 1

        job = await queue.get(seeded.job_id)
        run, events = await _load_run_and_events(factory, seeded.run_id)

        assert job is not None
        assert job.state is JobState.FAILED
        assert job.attempts == 2
        assert run is not None
        assert run.status is RunStatus.FAILED
        assert run.finished_at is not None

        event_types = [event.event_type for event in events]
        assert event_types.count(AgentEventType.RUN_STARTED) == 1
        assert event_types.count(AgentEventType.RUN_FAILED) == 1
        failed_event = next(
            event for event in events if event.event_type is AgentEventType.RUN_FAILED
        )
        assert failed_event.payload == {"error_code": "TimeoutError"}
        assert graph.execute_calls == 2
    finally:
        await _cleanup(factory, seeded)
        await engine.dispose()
