from __future__ import annotations

import pytest

from project_agent.workers.reaper import JobReaper


class FakeReapableQueue:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def reap_expired(self, *, limit: int) -> int:
        self.calls.append(limit)
        return 2


@pytest.mark.asyncio
async def test_reaper_recovers_expired_leases_without_claim_logic_coupling() -> None:
    queue = FakeReapableQueue()
    reaper = JobReaper(queue, batch_size=25)

    recovered = await reaper.run_once()

    assert recovered == 2
    assert queue.calls == [25]
