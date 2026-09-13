from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from project_agent.application.ports.job_queue import JobQueuePort, QueuedJob
from project_agent.workers.handlers import HandlerRegistry


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    concurrency: int = 4
    claim_limit: int = 4
    heartbeat_seconds: float = 15.0
    poll_seconds: float = 1.0


class BackgroundWorker:
    def __init__(
        self,
        queue: JobQueuePort,
        handlers: HandlerRegistry,
        *,
        worker_id: str,
        settings: WorkerSettings = WorkerSettings(),
    ) -> None:
        if settings.concurrency < 1:
            raise ValueError("worker concurrency must be >= 1")
        if settings.claim_limit < 1:
            raise ValueError("worker claim_limit must be >= 1")
        self._queue = queue
        self._handlers = handlers
        self._worker_id = worker_id
        self._settings = settings
        self._stop = asyncio.Event()

    async def run_once(self) -> int:
        jobs = await self._queue.claim(
            self._worker_id,
            limit=min(self._settings.concurrency, self._settings.claim_limit),
        )
        if not jobs:
            return 0
        await asyncio.gather(*(self._process(job) for job in jobs))
        return len(jobs)

    async def serve_forever(self) -> None:
        while not self._stop.is_set():
            count = await self.run_once()
            if count == 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._settings.poll_seconds)
                except TimeoutError:
                    pass

    def stop(self) -> None:
        self._stop.set()

    async def _process(self, job: QueuedJob) -> None:
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job.job_id))
        try:
            handler = self._handlers.resolve(job.job_type)
            await handler(job.aggregate_id)
        except Exception as exc:
            await self._queue.fail(job.job_id, self._worker_id, type(exc).__name__)
        else:
            await self._queue.complete(job.job_id, self._worker_id)
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _heartbeat_loop(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self._settings.heartbeat_seconds)
            await self._queue.heartbeat(job_id, self._worker_id)
