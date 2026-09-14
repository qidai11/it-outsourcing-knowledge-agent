from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_agent.application.ports.job_queue import (
    EnqueueJobRequest,
    JobState,
    QueuedJob,
)
from project_agent.infrastructure.db.models.schema import BackgroundJobModel


class JobOwnershipError(RuntimeError):
    pass


def compute_retry_delay(
    attempt_count: int,
    *,
    base_seconds: float,
    max_seconds: float,
) -> float:
    if base_seconds < 0 or max_seconds < 0:
        raise ValueError("retry delays cannot be negative")
    if base_seconds == 0:
        return 0.0
    return float(min(base_seconds * (2.0 ** max(0, attempt_count - 1)), max_seconds))


def should_retry(*, attempt_count: int, max_attempts: int) -> bool:
    return attempt_count < max_attempts


def build_claim_statement(*, limit: int) -> Select[tuple[BackgroundJobModel]]:
    return (
        select(BackgroundJobModel)
        .where(
            BackgroundJobModel.status == JobState.PENDING.value,
            BackgroundJobModel.available_at <= datetime.now(UTC),
        )
        .order_by(
            BackgroundJobModel.available_at,
            BackgroundJobModel.created_at,
            BackgroundJobModel.id,
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


class PostgresJobQueue:
    """PostgreSQL-backed queue using row locks and expiring worker leases."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: float = 60.0,
        retry_base_seconds: float = 5.0,
        retry_max_seconds: float = 300.0,
        namespace: str = "project-agent",
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if retry_base_seconds < 0 or retry_max_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        self._session_factory = session_factory
        self._lease = timedelta(seconds=lease_seconds)
        self._retry_base = retry_base_seconds
        self._retry_max = retry_max_seconds
        self._namespace = namespace

    async def enqueue(self, request: EnqueueJobRequest) -> QueuedJob:
        if not request.aggregate_id.strip():
            raise ValueError("aggregate_id is required")
        if request.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        row = BackgroundJobModel(
            namespace=self._namespace,
            job_type=request.job_type,
            aggregate_id=request.aggregate_id,
            status=JobState.PENDING.value,
            attempt_count=0,
            max_attempts=request.max_attempts,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._to_job(row)

    async def claim(self, worker_id: str, limit: int = 1) -> list[QueuedJob]:
        if limit < 1:
            return []
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            rows = list((await session.scalars(build_claim_statement(limit=limit))).all())
            for row in rows:
                row.status = JobState.RUNNING.value
                row.attempt_count += 1
                row.locked_by = worker_id
                row.locked_at = now
                row.heartbeat_at = now
                row.lease_expires_at = now + self._lease
                row.updated_at = now
            await session.commit()
            return [self._to_job(row) for row in rows]

    async def heartbeat(self, job_id: str, worker_id: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = await self._owned_running(session, job_id, worker_id)
            row.heartbeat_at = now
            row.lease_expires_at = now + self._lease
            row.updated_at = now
            await session.commit()

    async def complete(self, job_id: str, worker_id: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = await self._owned_running(session, job_id, worker_id)
            row.status = JobState.SUCCEEDED.value
            row.locked_by = None
            row.locked_at = None
            row.heartbeat_at = None
            row.lease_expires_at = None
            row.updated_at = now
            await session.commit()

    async def fail(self, job_id: str, worker_id: str, error_code: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = await self._owned_running(session, job_id, worker_id)
            row.last_error = error_code
            row.locked_by = None
            row.locked_at = None
            row.heartbeat_at = None
            row.lease_expires_at = None
            if not should_retry(attempt_count=row.attempt_count, max_attempts=row.max_attempts):
                row.status = JobState.FAILED.value
            else:
                row.status = JobState.PENDING.value
                row.available_at = now + timedelta(
                    seconds=compute_retry_delay(
                        row.attempt_count,
                        base_seconds=self._retry_base,
                        max_seconds=self._retry_max,
                    )
                )
            row.updated_at = now
            await session.commit()

    async def get(self, job_id: str) -> QueuedJob | None:
        async with self._session_factory() as session:
            row = await session.get(BackgroundJobModel, self._uuid(job_id))
            return None if row is None else self._to_job(row)

    async def reap_expired(self, *, limit: int = 100) -> int:
        now = datetime.now(UTC)
        stmt = (
            select(BackgroundJobModel)
            .where(
                BackgroundJobModel.status == JobState.RUNNING.value,
                BackgroundJobModel.lease_expires_at.is_not(None),
                BackgroundJobModel.lease_expires_at < now,
            )
            .order_by(BackgroundJobModel.lease_expires_at, BackgroundJobModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
            for row in rows:
                row.locked_by = None
                row.locked_at = None
                row.heartbeat_at = None
                row.lease_expires_at = None
                if not should_retry(attempt_count=row.attempt_count, max_attempts=row.max_attempts):
                    row.status = JobState.FAILED.value
                    row.last_error = row.last_error or "LEASE_EXPIRED_MAX_ATTEMPTS"
                else:
                    row.status = JobState.PENDING.value
                    row.available_at = now
                    row.last_error = "LEASE_EXPIRED"
                row.updated_at = now
            await session.commit()
            return len(rows)

    async def _owned_running(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
    ) -> BackgroundJobModel:
        stmt = (
            select(BackgroundJobModel)
            .where(BackgroundJobModel.id == self._uuid(job_id))
            .with_for_update()
        )
        row = (await session.scalars(stmt)).one_or_none()
        if row is None:
            raise LookupError(job_id)
        if row.status != JobState.RUNNING.value or row.locked_by != worker_id:
            raise JobOwnershipError("job is not owned by this worker")
        return row

    @staticmethod
    def _uuid(job_id: str) -> UUID:
        try:
            return UUID(job_id)
        except ValueError as exc:
            raise LookupError(job_id) from exc

    @staticmethod
    def _to_job(row: BackgroundJobModel) -> QueuedJob:
        return QueuedJob(
            job_id=str(row.id),
            job_type=row.job_type,
            aggregate_id=row.aggregate_id,
            state=JobState(row.status),
            attempts=row.attempt_count,
            max_attempts=row.max_attempts,
            worker_id=row.locked_by,
            last_error_code=row.last_error,
            available_at=row.available_at,
            lease_expires_at=row.lease_expires_at,
            heartbeat_at=row.heartbeat_at,
        )
