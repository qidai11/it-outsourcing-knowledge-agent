from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from project_agent.application.ports.job_queue import (
    EnqueueJobRequest,
    JobState,
    QueuedJob,
)


class FakeJobQueue:
    def __init__(self) -> None:
        self._jobs: dict[str, QueuedJob] = {}
        self.heartbeats: list[tuple[str, str]] = []

    async def enqueue(self, request: EnqueueJobRequest) -> QueuedJob:
        job = QueuedJob(
            job_id=f"job-{uuid4().hex}",
            job_type=request.job_type,
            aggregate_id=request.aggregate_id,
            state=JobState.PENDING,
            attempts=0,
            max_attempts=request.max_attempts,
        )
        self._jobs[job.job_id] = job
        return job

    async def claim(self, worker_id: str, limit: int = 1) -> list[QueuedJob]:
        claimed: list[QueuedJob] = []
        for job_id, job in list(self._jobs.items()):
            if len(claimed) >= limit:
                break
            if job.state is not JobState.PENDING:
                continue
            running = replace(
                job,
                state=JobState.RUNNING,
                attempts=job.attempts + 1,
                worker_id=worker_id,
            )
            self._jobs[job_id] = running
            claimed.append(running)
        return claimed

    async def heartbeat(self, job_id: str, worker_id: str) -> None:
        job = self._require_owned_running(job_id, worker_id)
        self.heartbeats.append((job.job_id, worker_id))

    async def complete(self, job_id: str, worker_id: str) -> None:
        job = self._require_owned_running(job_id, worker_id)
        self._jobs[job_id] = replace(job, state=JobState.SUCCEEDED)

    async def fail(self, job_id: str, worker_id: str, error_code: str) -> None:
        job = self._require_owned_running(job_id, worker_id)
        self._jobs[job_id] = replace(
            job,
            state=JobState.FAILED,
            last_error_code=error_code,
        )

    async def get(self, job_id: str) -> QueuedJob | None:
        return self._jobs.get(job_id)

    def _require_owned_running(self, job_id: str, worker_id: str) -> QueuedJob:
        job = self._jobs[job_id]
        if job.state is not JobState.RUNNING or job.worker_id != worker_id:
            raise RuntimeError("job is not owned by this worker")
        return job
