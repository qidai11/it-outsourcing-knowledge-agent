from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypedDict
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from project_agent.agent.checkpoint import async_postgres_saver
from project_agent.application.ports.job_queue import EnqueueJobRequest, JobState
from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunJobType, RunStatus
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    AuditLogModel,
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
from project_agent.workers.handlers import (
    EXECUTE_AGENT_RUN,
    RESUME_AGENT_RUN,
    HandlerRegistry,
)
from project_agent.workers.main import BackgroundWorker, WorkerSettings
from project_agent.workers.run_execution import ExecuteAgentRunHandler, ResumeAgentRunHandler

LIVE_POSTGRES = os.getenv("RUN_POSTGRES_INTEGRATION") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE_POSTGRES,
    reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL resume gate",
)

HASH = "a" * 64


class ResumeState(TypedDict, total=False):
    run_id: str
    thread_id: str
    user_id: str
    project_id: str
    route: str | None
    last_error_code: str | None
    resume: dict[str, object]


@dataclass(frozen=True, slots=True)
class SeededRun:
    client_id: UUID
    project_id: UUID
    thread_id: UUID
    run_id: UUID
    user_id: UUID
    execute_job_id: str
    side_effect_action: str


class CountingExecutor:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.execute_calls = 0
        self.resume_calls = 0

    async def execute(self, run):  # type: ignore[no-untyped-def]
        self.execute_calls += 1
        return await self._delegate.execute(run)

    async def resume(self, run, resume_payload):  # type: ignore[no-untyped-def]
        self.resume_calls += 1
        return await self._delegate.resume(run, resume_payload)


@dataclass(slots=True)
class LiveRuntime:
    engine: Any
    session_factory: Any
    queue: PostgresJobQueue
    worker: BackgroundWorker
    saver: Any
    executor: CountingExecutor


async def _seed_interrupt_run(database_url: str) -> SeededRun:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    company_id = uuid4()
    user_id = uuid4()
    manager_id = uuid4()
    client_id = uuid4()
    project_id = uuid4()
    thread_id = uuid4()
    run_id = uuid4()
    side_effect_action = f"ws3-task7-side-effect-{run_id}"

    try:
        async with factory() as session:
            session.add(
                ClientModel(
                    id=client_id,
                    company_id=company_id,
                    name=f"WS3 Resume Client {client_id}",
                )
            )
            await session.flush()

            session.add(
                ProjectModel(
                    id=project_id,
                    company_id=company_id,
                    client_id=client_id,
                    code=f"ws3-resume-{project_id.hex[:8]}",
                    name="WS3 Resume Integration",
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
                    business_mode=RunBusinessMode.ISSUE_CREATE.value,
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
                payload={"query_text": "interrupt and resume through postgres checkpoint"},
            )
            jobs = SqlAlchemySessionJobEnqueuer(session)
            execute_job = await jobs.enqueue(
                EnqueueJobRequest(
                    job_type=RunJobType.EXECUTE.value,
                    aggregate_id=str(run_id),
                )
            )
            await session.commit()
    finally:
        await engine.dispose()

    return SeededRun(
        client_id=client_id,
        project_id=project_id,
        thread_id=thread_id,
        run_id=run_id,
        user_id=user_id,
        execute_job_id=execute_job.job_id,
        side_effect_action=side_effect_action,
    )


def _build_resumable_graph(saver: Any, session_factory: Any, action: str) -> Any:
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    async def await_confirmation(state: ResumeState) -> ResumeState:
        del state
        resume = interrupt(
            {
                "request_payload_hash": HASH,
                "tool_name": "create_issue",
            }
        )
        return {"route": "resumed", "resume": dict(resume)}

    async def post_confirmation(state: ResumeState) -> ResumeState:
        async with session_factory() as session:
            session.add(
                AuditLogModel(
                    company_id=None,
                    project_id=UUID(state["project_id"]),
                    user_id=UUID(state["user_id"]),
                    action=action,
                    resource_type="ws3_checkpoint_resume",
                    resource_id=state["run_id"],
                    outcome="success",
                    details_json={"resume": dict(state["resume"])},
                )
            )
            await session.commit()
        return {"route": "resumed"}

    graph = StateGraph(ResumeState)
    graph.add_node("await_confirmation", await_confirmation)
    graph.add_node("post_confirmation", post_confirmation)
    graph.add_edge(START, "await_confirmation")
    graph.add_edge("await_confirmation", "post_confirmation")
    graph.add_edge("post_confirmation", END)
    return graph.compile(checkpointer=saver)


@asynccontextmanager
async def _runtime(database_url: str, *, action: str) -> AsyncIterator[LiveRuntime]:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    queue = PostgresJobQueue(factory, retry_base_seconds=0, retry_max_seconds=0)

    try:
        async with async_postgres_saver(database_url) as saver:
            from project_agent.workers.run_graph import LangGraphRunExecutor

            compiled = _build_resumable_graph(saver, factory, action)
            graph = CountingExecutor(
                LangGraphRunExecutor({RunBusinessMode.ISSUE_CREATE: compiled})
            )
            handlers = HandlerRegistry()
            handlers.register(EXECUTE_AGENT_RUN, ExecuteAgentRunHandler(factory, graph))
            handlers.register(RESUME_AGENT_RUN, ResumeAgentRunHandler(factory, graph))
            worker = BackgroundWorker(
                queue,
                handlers,
                worker_id=f"ws3-resume-{uuid4()}",
                settings=WorkerSettings(
                    concurrency=1,
                    claim_limit=1,
                    heartbeat_seconds=60,
                    poll_seconds=0.01,
                ),
            )
            yield LiveRuntime(
                engine=engine,
                session_factory=factory,
                queue=queue,
                worker=worker,
                saver=saver,
                executor=graph,
            )
    finally:
        await engine.dispose()


async def _load_run_events(database_url: str, run_id: UUID):  # type: ignore[no-untyped-def]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            repo = SqlAlchemyRunRepository(session)
            run = await repo.get_run(run_id)
            events = await repo.list_events_after(run_id=run_id, after_sequence=0, limit=100)
            return run, events
    finally:
        await engine.dispose()


async def _persist_resume_intent(database_url: str, seeded: SeededRun) -> str:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            repo = SqlAlchemyRunRepository(session)
            await repo.append_event(
                run_id=seeded.run_id,
                event_type=AgentEventType.RUN_RESUME_QUEUED,
                payload={
                    "action": "confirm",
                    "request_payload_hash": HASH,
                    "actor_id": str(seeded.user_id),
                },
            )
            await repo.set_status(run_id=seeded.run_id, status=RunStatus.QUEUED)
            jobs = SqlAlchemySessionJobEnqueuer(session)
            queued = await jobs.enqueue(
                EnqueueJobRequest(
                    job_type=RunJobType.RESUME.value,
                    aggregate_id=str(seeded.run_id),
                )
            )
            await session.commit()
            return queued.job_id
    finally:
        await engine.dispose()


async def _side_effect_count(database_url: str, action: str) -> int:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            result = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(AuditLogModel.action == action)
            )
            return int(result or 0)
    finally:
        await engine.dispose()


async def _cleanup(database_url: str, seeded: SeededRun) -> None:
    async with async_postgres_saver(database_url) as saver:
        await saver.adelete_thread(str(seeded.thread_id))

    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            await session.execute(
                delete(AuditLogModel).where(AuditLogModel.action == seeded.side_effect_action)
            )
            await session.execute(
                delete(BackgroundJobModel).where(
                    BackgroundJobModel.aggregate_id == str(seeded.run_id)
                )
            )
            await session.execute(
                delete(AgentEventModel).where(AgentEventModel.run_id == seeded.run_id)
            )
            await session.execute(delete(AgentRunModel).where(AgentRunModel.id == seeded.run_id))
            await session.execute(delete(ThreadModel).where(ThreadModel.id == seeded.thread_id))
            await session.execute(delete(ProjectModel).where(ProjectModel.id == seeded.project_id))
            await session.execute(delete(ClientModel).where(ClientModel.id == seeded.client_id))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resume_uses_postgres_checkpoint_across_runtime_boundary() -> None:
    pytest.importorskip(
        "langgraph.checkpoint.postgres.aio",
        reason="langgraph-checkpoint-postgres is required for the live resume gate",
    )
    database_url = os.environ["DATABASE_URL"]
    seeded = await _seed_interrupt_run(database_url)

    try:
        async with _runtime(database_url, action=seeded.side_effect_action) as first:
            assert await first.worker.run_once() == 1

            execute_job = await first.queue.get(seeded.execute_job_id)
            run, events = await _load_run_events(database_url, seeded.run_id)
            checkpoint = await first.saver.aget_tuple(
                {"configurable": {"thread_id": str(seeded.thread_id)}}
            )

            assert execute_job is not None
            assert execute_job.state is JobState.SUCCEEDED
            assert run is not None
            assert run.status is RunStatus.WAITING_CONFIRMATION
            assert run.finished_at is None
            assert first.executor.execute_calls == 1
            assert first.executor.resume_calls == 0
            assert checkpoint is not None
            assert await _side_effect_count(database_url, seeded.side_effect_action) == 0

            waiting = [
                event
                for event in events
                if event.event_type is AgentEventType.WAITING_CONFIRMATION
            ]
            assert len(waiting) == 1
            assert waiting[0].payload["request_payload_hash"] == HASH

        resume_job_id = await _persist_resume_intent(database_url, seeded)

        async with _runtime(database_url, action=seeded.side_effect_action) as second:
            assert await second.worker.run_once() == 1

            resume_job = await second.queue.get(resume_job_id)
            run, events = await _load_run_events(database_url, seeded.run_id)

            assert resume_job is not None
            assert resume_job.state is JobState.SUCCEEDED
            assert run is not None
            assert run.status is RunStatus.SUCCEEDED
            assert run.finished_at is not None
            assert second.executor.execute_calls == 0
            assert second.executor.resume_calls == 1
            assert await _side_effect_count(database_url, seeded.side_effect_action) == 1

            event_types = [event.event_type for event in events]
            assert event_types.count(AgentEventType.RUN_RESUMED) == 1
            assert event_types.count(AgentEventType.RUN_SUCCEEDED) == 1

            duplicate = await second.queue.enqueue(
                EnqueueJobRequest(
                    job_type=RunJobType.RESUME.value,
                    aggregate_id=str(seeded.run_id),
                )
            )
            assert await second.worker.run_once() == 1

            duplicate_job = await second.queue.get(duplicate.job_id)
            _, duplicate_events = await _load_run_events(database_url, seeded.run_id)
            duplicate_types = [event.event_type for event in duplicate_events]

            assert duplicate_job is not None
            assert duplicate_job.state is JobState.SUCCEEDED
            assert second.executor.resume_calls == 1
            assert await _side_effect_count(database_url, seeded.side_effect_action) == 1
            assert duplicate_types.count(AgentEventType.RUN_RESUMED) == 1
            assert duplicate_types.count(AgentEventType.RUN_SUCCEEDED) == 1
    finally:
        await _cleanup(database_url, seeded)
