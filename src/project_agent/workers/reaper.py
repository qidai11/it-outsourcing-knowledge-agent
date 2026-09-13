from __future__ import annotations

from typing import Protocol


class ReapableJobQueue(Protocol):
    async def reap_expired(self, *, limit: int) -> int: ...


class JobReaper:
    def __init__(self, queue: ReapableJobQueue, *, batch_size: int = 100) -> None:
        self._queue = queue
        self._batch_size = batch_size

    async def run_once(self) -> int:
        return await self._queue.reap_expired(limit=self._batch_size)
