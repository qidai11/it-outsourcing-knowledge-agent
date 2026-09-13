from __future__ import annotations

import pytest

from project_agent.workers.rate_limit import RateLimitWaitTimeout, TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_token_bucket_refills_without_real_sleep() -> None:
    clock = FakeClock()
    bucket = TokenBucket(
        capacity=2,
        refill_rate_per_second=1.0,
        clock=clock,
        sleep=clock.sleep,
    )

    await bucket.acquire(2, timeout=0)
    await bucket.acquire(1, timeout=1.1)

    assert clock.now == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_token_bucket_returns_explicit_timeout() -> None:
    clock = FakeClock()
    bucket = TokenBucket(
        capacity=1,
        refill_rate_per_second=0.1,
        clock=clock,
        sleep=clock.sleep,
    )
    await bucket.acquire(1, timeout=0)

    with pytest.raises(RateLimitWaitTimeout):
        await bucket.acquire(1, timeout=0.5)


@pytest.mark.asyncio
async def test_token_bucket_rejects_amount_over_capacity() -> None:
    bucket = TokenBucket(capacity=2, refill_rate_per_second=1)

    with pytest.raises(ValueError, match="capacity"):
        await bucket.acquire(3, timeout=1)

@pytest.mark.asyncio
async def test_model_aliases_have_independent_process_local_buckets() -> None:
    from project_agent.workers.rate_limit import ModelTokenBucketRegistry

    limiter = ModelTokenBucketRegistry(request_capacity=1, token_capacity=10, window_seconds=1000)
    await limiter.acquire("model-a", estimated_tokens=10, timeout=0)
    await limiter.acquire("model-b", estimated_tokens=10, timeout=0)

    with pytest.raises(RateLimitWaitTimeout):
        await limiter.acquire("model-a", estimated_tokens=1, timeout=0)
