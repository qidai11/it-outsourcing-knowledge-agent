from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest

from project_agent.application.ports.job_queue import JobState, QueuedJob
from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind
from project_agent.application.services.run_execution import RunExecutionService
from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunStatus
from project_agent.workers.run_execution import ExecuteAgentRunHandler, ResumeAgentRunHandler
from tests.fakes.run_graph import FakeRunGraphExecutor
from tests.fakes.run_repository import FakeRunRepository

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


class FakeSession:
    def __init__(self, owner: FakeSessionFactory) -> None:
        self._owner = owner

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    async def commit(self) -> None:
        self._owner.commits += 1


class FakeSessionFactory:
    def __init__(self) -> None:
        self.commits = 0

    def __call__(self) -> FakeSession:
        return FakeSession(self)


class RaisingGraph(FakeRunGraphExecutor):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    async def execute(self, run):  # type: ignore[no-untyped-def]
        self.execute_calls.append(run)
        raise self._exc

    async def resume(self, run, resume_payload):  # type: ignore[no-untyped-def]
        self.resume_calls.append((run, dict(resume_payload)))
        raise self._exc


class CommitObservingGraph(FakeRunGraphExecutor):
    def __init__(self, sessions: FakeSessionFactory) -> None:
        super().__init__()
        self._sessions = sessions
        self.commits_seen: list[int] = []

    async def execute(self, run):  # type: ignore[no-untyped-def]
        self.commits_seen.append(self._sessions.commits)
        return await super().execute(run)


async def seeded_run(
    repo: FakeRunRepository,
    *,
    status: RunStatus = RunStatus.QUEUED,
) -> UUID:
    thread = await repo.create_thread(
        company_id=UUID("00000000-0000-0000-0000-000000000001"),
        project_id=UUID("00000000-0000-0000-0000-000000000002"),
        user_id=UUID("00000000-0000-0000-0000-000000000003"),
    )
    run = await repo.create_run(
        thread_id=thread.id,
        company_id=thread.company_id,
        project_id=thread.project_id,
        user_id=thread.user_id,
        business_mode=RunBusinessMode.ISSUE_CREATE,
    )
    if status is not RunStatus.QUEUED:
        await repo.set_lifecycle(
            run_id=run.id,
            status=status,
            started_at=NOW if status is not RunStatus.QUEUED else None,
            finished_at=NOW if status in {RunStatus.SUCCEEDED, RunStatus.FAILED} else None,
        )
    return run.id


def claimed_job(run_id: UUID, *, attempts: int = 1, max_attempts: int = 3) -> QueuedJob:
    return QueuedJob(
        job_id="job-1",
        job_type="EXECUTE_AGENT_RUN",
        aggregate_id=str(run_id),
        state=JobState.RUNNING,
        attempts=attempts,
        max_attempts=max_attempts,
        worker_id="worker-1",
        last_error_code=None,
        available_at=None,
        lease_expires_at=None,
        heartbeat_at=None,
    )


def build_execute_handler(
    repo: FakeRunRepository,
    graph: FakeRunGraphExecutor,
    sessions: FakeSessionFactory,
) -> ExecuteAgentRunHandler:
    return ExecuteAgentRunHandler(
        cast(Any, sessions),
        graph,
        service_factory=lambda _session: RunExecutionService(repo, clock=lambda: NOW),
    )


def build_resume_handler(
    repo: FakeRunRepository,
    graph: FakeRunGraphExecutor,
    sessions: FakeSessionFactory,
) -> ResumeAgentRunHandler:
    return ResumeAgentRunHandler(
        cast(Any, sessions),
        graph,
        service_factory=lambda _session: RunExecutionService(repo, clock=lambda: NOW),
    )


@pytest.mark.asyncio
async def test_execute_handler_commits_prepare_before_graph_and_persists_success() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo)
    await repo.append_event(
        run_id=run_id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"query_text": "hello"},
    )
    sessions = FakeSessionFactory()
    graph = CommitObservingGraph(sessions)

    await build_execute_handler(repo, graph, sessions)(claimed_job(run_id))

    assert graph.commits_seen == [1]
    assert len(graph.execute_calls) == 1
    assert sessions.commits == 2
    assert repo.runs[run_id].status is RunStatus.SUCCEEDED
    assert [event.event_type for event in repo.events[run_id]].count(
        AgentEventType.RUN_SUCCEEDED
    ) == 1


@pytest.mark.asyncio
async def test_resume_handler_uses_durable_resume_payload_and_persists_success() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo, status=RunStatus.RUNNING)
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_QUEUED, payload={})
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_STARTED, payload={})
    await repo.append_event(
        run_id=run_id,
        event_type=AgentEventType.WAITING_CONFIRMATION,
        payload={"request_payload_hash": "a" * 64},
    )
    await repo.append_event(
        run_id=run_id,
        event_type=AgentEventType.RUN_RESUME_QUEUED,
        payload={
            "action": "confirm",
            "request_payload_hash": "a" * 64,
            "actor_id": "00000000-0000-0000-0000-000000000003",
        },
    )
    await repo.set_status(run_id=run_id, status=RunStatus.QUEUED)
    sessions = FakeSessionFactory()
    graph = FakeRunGraphExecutor()

    await build_resume_handler(repo, graph, sessions)(claimed_job(run_id))

    assert len(graph.resume_calls) == 1
    assert graph.resume_calls[0][1] == {
        "action": "confirm",
        "request_payload_hash": "a" * 64,
        "actor_id": "00000000-0000-0000-0000-000000000003",
    }
    assert repo.runs[run_id].status is RunStatus.SUCCEEDED
    assert [event.event_type for event in repo.events[run_id]].count(
        AgentEventType.RUN_RESUMED
    ) == 1


@pytest.mark.asyncio
async def test_waiting_outcome_keeps_finished_at_null() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo)
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_QUEUED, payload={})
    graph = FakeRunGraphExecutor(
        execute_outcome=RunGraphOutcome(
            kind=RunGraphOutcomeKind.WAITING_CONFIRMATION,
            waiting_payload={"request_payload_hash": "a" * 64},
        )
    )

    await build_execute_handler(repo, graph, FakeSessionFactory())(claimed_job(run_id))

    assert repo.runs[run_id].status is RunStatus.WAITING_CONFIRMATION
    assert repo.runs[run_id].finished_at is None


@pytest.mark.asyncio
async def test_execute_retry_does_not_duplicate_run_started() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo, status=RunStatus.RUNNING)
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_QUEUED, payload={})
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_STARTED, payload={})
    graph = FakeRunGraphExecutor()

    await build_execute_handler(repo, graph, FakeSessionFactory())(claimed_job(run_id, attempts=2))

    assert len(graph.execute_calls) == 1
    assert [event.event_type for event in repo.events[run_id]].count(
        AgentEventType.RUN_STARTED
    ) == 1


@pytest.mark.asyncio
async def test_resume_retry_does_not_duplicate_run_resumed() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo, status=RunStatus.RUNNING)
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_QUEUED, payload={})
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_STARTED, payload={})
    await repo.append_event(
        run_id=run_id,
        event_type=AgentEventType.RUN_RESUME_QUEUED,
        payload={"action": "confirm", "request_payload_hash": "a" * 64},
    )
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_RESUMED, payload={})
    graph = FakeRunGraphExecutor()

    await build_resume_handler(repo, graph, FakeSessionFactory())(
        claimed_job(run_id, attempts=2)
    )

    assert len(graph.resume_calls) == 1
    assert [event.event_type for event in repo.events[run_id]].count(
        AgentEventType.RUN_RESUMED
    ) == 1


@pytest.mark.asyncio
async def test_terminal_execute_retry_is_noop() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo, status=RunStatus.SUCCEEDED)
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_QUEUED, payload={})
    graph = FakeRunGraphExecutor()

    await build_execute_handler(repo, graph, FakeSessionFactory())(claimed_job(run_id))

    assert graph.execute_calls == []


@pytest.mark.asyncio
async def test_stale_execute_after_resume_intent_is_noop() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo, status=RunStatus.RUNNING)
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_QUEUED, payload={})
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_STARTED, payload={})
    await repo.append_event(
        run_id=run_id,
        event_type=AgentEventType.RUN_RESUME_QUEUED,
        payload={"action": "confirm", "request_payload_hash": "a" * 64},
    )
    graph = FakeRunGraphExecutor()

    await build_execute_handler(repo, graph, FakeSessionFactory())(claimed_job(run_id))

    assert graph.execute_calls == []


@pytest.mark.asyncio
async def test_intermediate_graph_failure_re_raises_without_run_failed() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo)
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_QUEUED, payload={})
    graph = RaisingGraph(TimeoutError("provider timeout"))

    with pytest.raises(TimeoutError):
        await build_execute_handler(repo, graph, FakeSessionFactory())(
            claimed_job(run_id, attempts=1, max_attempts=3)
        )

    assert repo.runs[run_id].status is RunStatus.RUNNING
    assert [event.event_type for event in repo.events[run_id]].count(
        AgentEventType.RUN_FAILED
    ) == 0


@pytest.mark.asyncio
async def test_final_graph_failure_marks_run_failed_once_and_re_raises() -> None:
    repo = FakeRunRepository()
    run_id = await seeded_run(repo)
    await repo.append_event(run_id=run_id, event_type=AgentEventType.RUN_QUEUED, payload={})
    graph = RaisingGraph(TimeoutError("provider timeout"))
    handler = build_execute_handler(repo, graph, FakeSessionFactory())
    job = claimed_job(run_id, attempts=3, max_attempts=3)

    with pytest.raises(TimeoutError):
        await handler(job)
    await handler(job)

    assert repo.runs[run_id].status is RunStatus.FAILED
    failed = [
        event for event in repo.events[run_id] if event.event_type is AgentEventType.RUN_FAILED
    ]
    assert len(failed) == 1
    assert failed[0].payload == {"error_code": "TimeoutError"}
    assert len(graph.execute_calls) == 1
