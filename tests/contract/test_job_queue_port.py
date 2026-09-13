from __future__ import annotations

import pytest

from project_agent.application.ports.job_queue import EnqueueJobRequest, JobQueuePort, JobState
from tests.fakes.job_queue import FakeJobQueue


@pytest.mark.asyncio
async def test_fake_job_queue_claim_complete_contract() -> None:
    queue = FakeJobQueue()
    assert isinstance(queue, JobQueuePort)

    queued = await queue.enqueue(
        EnqueueJobRequest(job_type="DOCUMENT_INGEST", aggregate_id="doc-v1")
    )
    assert queued.state is JobState.PENDING

    claimed = await queue.claim(worker_id="worker-1", limit=1)
    assert len(claimed) == 1
    assert claimed[0].job_id == queued.job_id
    assert claimed[0].state is JobState.RUNNING

    await queue.complete(job_id=queued.job_id, worker_id="worker-1")
    completed = await queue.get(queued.job_id)
    assert completed is not None
    assert completed.state is JobState.SUCCEEDED


@pytest.mark.asyncio
async def test_fake_job_queue_does_not_claim_same_job_twice() -> None:
    queue = FakeJobQueue()
    await queue.enqueue(EnqueueJobRequest(job_type="RUN_AGENT", aggregate_id="run-1"))

    first = await queue.claim(worker_id="worker-1", limit=1)
    second = await queue.claim(worker_id="worker-2", limit=1)

    assert len(first) == 1
    assert second == []
