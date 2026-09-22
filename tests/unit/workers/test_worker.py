from __future__ import annotations

import pytest

from project_agent.application.ports.job_queue import EnqueueJobRequest, JobState, QueuedJob
from project_agent.workers.handlers import AggregateIdHandlerAdapter, HandlerRegistry
from project_agent.workers.main import BackgroundWorker, WorkerSettings
from tests.fakes.job_queue import FakeJobQueue


@pytest.mark.asyncio
async def test_worker_completes_successful_job() -> None:
    queue = FakeJobQueue()
    job = await queue.enqueue(EnqueueJobRequest(job_type="TEST", aggregate_id="agg-1"))
    calls: list[str] = []

    async def handler(aggregate_id: str) -> None:
        calls.append(aggregate_id)

    handlers = HandlerRegistry()
    handlers.register("TEST", AggregateIdHandlerAdapter(handler))
    worker = BackgroundWorker(
        queue,
        handlers,
        worker_id="worker-1",
        settings=WorkerSettings(concurrency=1, heartbeat_seconds=60, poll_seconds=0.01),
    )

    assert await worker.run_once() == 1
    saved = await queue.get(job.job_id)
    assert saved is not None
    assert saved.state is JobState.SUCCEEDED
    assert calls == ["agg-1"]


@pytest.mark.asyncio
async def test_worker_failure_is_recorded_by_queue() -> None:
    queue = FakeJobQueue()
    job = await queue.enqueue(EnqueueJobRequest(job_type="TEST", aggregate_id="agg-2"))

    async def handler(_: QueuedJob) -> None:
        raise RuntimeError("boom")

    handlers = HandlerRegistry()
    handlers.register("TEST", handler)
    worker = BackgroundWorker(
        queue,
        handlers,
        worker_id="worker-1",
        settings=WorkerSettings(concurrency=1, heartbeat_seconds=60, poll_seconds=0.01),
    )

    await worker.run_once()
    saved = await queue.get(job.job_id)
    assert saved is not None
    assert saved.state is JobState.FAILED
    assert saved.last_error_code == "RuntimeError"


@pytest.mark.asyncio
async def test_worker_passes_claimed_attempt_metadata_to_handler() -> None:
    queue = FakeJobQueue()
    queued = await queue.enqueue(
        EnqueueJobRequest(job_type="TEST", aggregate_id="agg-ctx", max_attempts=4)
    )
    seen: list[QueuedJob] = []

    async def handler(job: QueuedJob) -> None:
        seen.append(job)

    handlers = HandlerRegistry()
    handlers.register("TEST", handler)
    worker = BackgroundWorker(
        queue,
        handlers,
        worker_id="worker-1",
        settings=WorkerSettings(concurrency=1, heartbeat_seconds=60, poll_seconds=0.01),
    )

    assert await worker.run_once() == 1
    assert len(seen) == 1
    assert seen[0].job_id == queued.job_id
    assert seen[0].aggregate_id == "agg-ctx"
    assert seen[0].attempts == 1
    assert seen[0].max_attempts == 4


@pytest.mark.asyncio
async def test_worker_context_is_isolated_between_concurrent_jobs() -> None:
    from structlog.contextvars import get_contextvars

    from project_agent.observability.metrics import ObservabilityMetrics

    queue = FakeJobQueue()
    await queue.enqueue(EnqueueJobRequest(job_type="TEST", aggregate_id="left"))
    await queue.enqueue(EnqueueJobRequest(job_type="TEST", aggregate_id="right"))
    seen: list[tuple[str, str, int]] = []

    async def handler(job: QueuedJob) -> None:
        await __import__("asyncio").sleep(0)
        ctx = get_contextvars()
        seen.append((str(ctx["job_id"]), str(ctx["job_type"]), int(ctx["attempt_count"])))

    handlers = HandlerRegistry()
    handlers.register("TEST", handler)
    worker = BackgroundWorker(
        queue, handlers, worker_id="worker-ctx",
        settings=WorkerSettings(concurrency=2, claim_limit=2, heartbeat_seconds=60),
        metrics=ObservabilityMetrics(),
    )
    assert await worker.run_once() == 2
    assert len({item[0] for item in seen}) == 2
    assert {item[1] for item in seen} == {"TEST"}
    assert {item[2] for item in seen} == {1}
    assert get_contextvars() == {}
