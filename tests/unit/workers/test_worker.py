from __future__ import annotations

import pytest

from project_agent.application.ports.job_queue import EnqueueJobRequest, JobState
from project_agent.workers.handlers import HandlerRegistry
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
    handlers.register("TEST", handler)
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

    async def handler(_: str) -> None:
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
