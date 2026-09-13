from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class RateLimitWaitTimeout(TimeoutError):
    pass


class TokenBucket:
    def __init__(
        self,
        *,
        capacity: float,
        refill_rate_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate_per_second <= 0:
            raise ValueError("refill rate must be positive")
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate_per_second)
        self._tokens = float(capacity)
        self._clock = clock
        self._sleep = sleep
        self._updated_at = clock()
        self._lock = asyncio.Lock()

    async def acquire(self, amount: float = 1, *, timeout: float) -> None:
        if amount <= 0:
            return
        if amount > self.capacity:
            raise ValueError("requested amount exceeds bucket capacity")
        deadline = self._clock() + max(0.0, timeout)
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                wait_for = (amount - self._tokens) / self.refill_rate
                remaining = deadline - self._clock()
                if wait_for > remaining:
                    raise RateLimitWaitTimeout(
                        f"token bucket wait exceeds timeout ({timeout}s)"
                    )
            await self._sleep(wait_for)

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._updated_at)
        if elapsed:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._updated_at = now


class ModelTokenBucketRegistry:
    """Process-local request/token buckets keyed by model alias."""

    def __init__(
        self,
        *,
        request_capacity: int,
        token_capacity: int,
        window_seconds: float = 60,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._request_capacity = request_capacity
        self._token_capacity = token_capacity
        self._window = window_seconds
        self._buckets: dict[str, tuple[TokenBucket, TokenBucket]] = {}

    async def acquire(self, model_alias: str, *, estimated_tokens: int, timeout: float) -> None:
        request_bucket, token_bucket = self._buckets_for(model_alias)
        await request_bucket.acquire(1, timeout=timeout)
        await token_bucket.acquire(max(1, estimated_tokens), timeout=timeout)

    def _buckets_for(self, model_alias: str) -> tuple[TokenBucket, TokenBucket]:
        if model_alias not in self._buckets:
            self._buckets[model_alias] = (
                TokenBucket(
                    capacity=self._request_capacity,
                    refill_rate_per_second=self._request_capacity / self._window,
                ),
                TokenBucket(
                    capacity=self._token_capacity,
                    refill_rate_per_second=self._token_capacity / self._window,
                ),
            )
        return self._buckets[model_alias]
