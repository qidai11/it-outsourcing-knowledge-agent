from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from project_agent.application.ports.job_queue import EnqueueJobRequest
from project_agent.infrastructure.db.models.schema import BackgroundJobModel
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.jobs.postgres import PostgresJobQueue
from project_agent.observability.metrics import ObservabilityMetrics

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run WS6 queue telemetry gate",
)


@pytest.mark.asyncio
async def test_queue_metrics_cover_claim_completion_failure_and_reaper() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    metrics = ObservabilityMetrics()
    queue = PostgresJobQueue(
        factory,
        lease_seconds=60,
        retry_base_seconds=0,
        retry_max_seconds=0,
        metrics=metrics,
    )
    created = []
    try:
        complete = await queue.enqueue(
            EnqueueJobRequest("TEST_COMPLETE", f"ws6-{uuid4()}")
        )
        created.append(complete)
        claimed = await queue.claim("worker-complete")
        assert [job.job_id for job in claimed] == [complete.job_id]
        await queue.complete(complete.job_id, "worker-complete")

        retry = await queue.enqueue(
            EnqueueJobRequest("TEST_RETRY", f"ws6-{uuid4()}", max_attempts=2)
        )
        created.append(retry)
        claimed = await queue.claim("worker-retry")
        assert [job.job_id for job in claimed] == [retry.job_id]
        await queue.fail(retry.job_id, "worker-retry", "RuntimeError")

        # retry_base_seconds=0 makes the retry immediately claimable again.
        # Finalize it before starting the independent final-failure scenario so
        # FIFO claim ordering cannot make the previous scenario interfere.
        claimed = await queue.claim("worker-retry-final")
        assert [job.job_id for job in claimed] == [retry.job_id]
        await queue.complete(retry.job_id, "worker-retry-final")

        failed = await queue.enqueue(
            EnqueueJobRequest("TEST_FAILED", f"ws6-{uuid4()}", max_attempts=1)
        )
        created.append(failed)
        claimed = await queue.claim("worker-failed")
        assert [job.job_id for job in claimed] == [failed.job_id]
        await queue.fail(failed.job_id, "worker-failed", "RuntimeError")

        reap_retry = await queue.enqueue(
            EnqueueJobRequest("TEST_REAP_RETRY", f"ws6-{uuid4()}", max_attempts=2)
        )
        reap_failed = await queue.enqueue(
            EnqueueJobRequest("TEST_REAP_FAILED", f"ws6-{uuid4()}", max_attempts=1)
        )
        created.extend([reap_retry, reap_failed])
        claimed = await queue.claim("worker-reaper", limit=2)
        assert {job.job_id for job in claimed} == {reap_retry.job_id, reap_failed.job_id}

        async with factory() as session:
            for job in (reap_retry, reap_failed):
                row = await session.get(BackgroundJobModel, UUID(job.job_id))
                assert row is not None
                row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        assert await queue.reap_expired(limit=10) >= 2

        rendered = metrics.render_latest().decode()
        assert (
            'project_agent_queue_completions_total{job_type="TEST_COMPLETE"} 1.0'
            in rendered
        )
        assert (
            'project_agent_queue_failures_total{job_type="TEST_RETRY",outcome="retry"} 1.0'
            in rendered
        )
        assert (
            'project_agent_queue_failures_total{job_type="TEST_FAILED",outcome="failed"} 1.0'
            in rendered
        )
        assert (
            'project_agent_queue_reaped_total{job_type="TEST_REAP_RETRY",outcome="retry"} 1.0'
            in rendered
        )
        assert (
            'project_agent_queue_reaped_total{job_type="TEST_REAP_FAILED",outcome="failed"} 1.0'
            in rendered
        )
        for job in created:
            assert job.job_id not in rendered
            assert job.aggregate_id not in rendered
    finally:
        if created:
            async with factory() as session:
                await session.execute(
                    delete(BackgroundJobModel).where(
                        BackgroundJobModel.id.in_([UUID(job.job_id) for job in created])
                    )
                )
                await session.commit()
        await engine.dispose()
