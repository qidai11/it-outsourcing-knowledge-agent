from __future__ import annotations

import asyncio

import pytest

from project_agent.workers.concurrency import ParseConcurrencyLimiter


@pytest.mark.asyncio
async def test_parse_semaphore_limits_active_parses_to_configured_capacity() -> None:
    limiter = ParseConcurrencyLimiter(max_concurrency=2)
    active = 0
    max_active = 0
    guard = asyncio.Lock()

    async def parse_one() -> None:
        nonlocal active, max_active
        async with limiter.slot():
            async with guard:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            async with guard:
                active -= 1

    await asyncio.gather(*(parse_one() for _ in range(8)))

    assert max_active == 2
