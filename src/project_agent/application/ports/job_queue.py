from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class EnqueueJobRequest:
    job_type: str
    aggregate_id: str
    max_attempts: int = 3


@dataclass(frozen=True, slots=True)
class QueuedJob:
    job_id: str
    job_type: str
    aggregate_id: str
    state: JobState
    attempts: int
    max_attempts: int
    worker_id: str | None = None
    last_error_code: str | None = None
    available_at: datetime | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None


@runtime_checkable
class JobEnqueuePort(Protocol):
    async def enqueue(self, request: EnqueueJobRequest) -> QueuedJob: ...


@runtime_checkable
class JobQueuePort(JobEnqueuePort, Protocol):
    async def claim(self, worker_id: str, limit: int = 1) -> list[QueuedJob]: ...

    async def heartbeat(self, job_id: str, worker_id: str) -> None: ...

    async def complete(self, job_id: str, worker_id: str) -> None: ...

    async def fail(self, job_id: str, worker_id: str, error_code: str) -> None: ...

    async def get(self, job_id: str) -> QueuedJob | None: ...
