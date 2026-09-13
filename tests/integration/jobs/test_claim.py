from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql

from project_agent.application.ports.job_queue import EnqueueJobRequest, JobState
from project_agent.infrastructure.db.models.schema import BackgroundJobModel
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.jobs.postgres import PostgresJobQueue, build_claim_statement


def test_claim_sql_uses_for_update_skip_locked() -> None:
    sql = str(
        build_claim_statement(limit=2).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "STATUS = 'PENDING'" in sql
    assert "AVAILABLE_AT" in sql


def test_background_job_schema_stores_aggregate_id_not_payload() -> None:
    columns = set(BackgroundJobModel.__table__.columns.keys())
    assert "aggregate_id" in columns
    assert "payload_json" not in columns
    assert "lease_expires_at" in columns
    assert "heartbeat_at" in columns


@pytest.mark.asyncio
async def test_two_workers_never_claim_same_postgres_job() -> None:
    if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL queue gate")

    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    factory = create_session_factory(engine)
    queue = PostgresJobQueue(factory, lease_seconds=60, retry_base_seconds=1, retry_max_seconds=10)
    aggregate_id = f"task8-claim-{uuid4()}"
    created = await queue.enqueue(EnqueueJobRequest(job_type="TEST", aggregate_id=aggregate_id))

    try:
        left, right = await asyncio.gather(queue.claim("worker-a"), queue.claim("worker-b"))
        claimed = [*left, *right]
        assert len(claimed) == 1
        assert claimed[0].job_id == created.job_id
        assert claimed[0].state is JobState.RUNNING
        assert claimed[0].attempts == 1
    finally:
        async with factory() as session:
            await session.execute(delete(BackgroundJobModel).where(BackgroundJobModel.id == UUID(created.job_id)))
            await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_expired_lease_is_reaped_and_can_be_claimed_again() -> None:
    if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL queue gate")

    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    factory = create_session_factory(engine)
    queue = PostgresJobQueue(factory, lease_seconds=60, retry_base_seconds=0, retry_max_seconds=0)
    created = await queue.enqueue(EnqueueJobRequest(job_type="TEST", aggregate_id=f"task8-reap-{uuid4()}"))

    try:
        first = await queue.claim("dead-worker")
        assert len(first) == 1
        async with factory() as session:
            row = await session.get(BackgroundJobModel, created.job_id)
            assert row is not None
            from datetime import UTC, datetime, timedelta
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        reaped = await queue.reap_expired(limit=10)
        assert reaped == 1
        second = await queue.claim("replacement-worker")
        assert len(second) == 1
        assert second[0].job_id == created.job_id
        assert second[0].attempts == 2
    finally:
        async with factory() as session:
            await session.execute(delete(BackgroundJobModel).where(BackgroundJobModel.id == UUID(created.job_id)))
            await session.commit()
        await engine.dispose()
