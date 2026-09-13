from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator


class ParseConcurrencyLimiter:
    def __init__(self, *, max_concurrency: int = 2) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._semaphore:
            yield
