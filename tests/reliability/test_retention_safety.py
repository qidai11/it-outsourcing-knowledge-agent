from __future__ import annotations

import pytest

from project_agent.application.ports.job_queue import JobState, QueuedJob
from project_agent.workers.retention import (
    RetentionCandidate,
    RetentionSweepHandler,
)


def retention_job() -> QueuedJob:
    return QueuedJob(
        job_id="job-retention",
        job_type="RETENTION_SWEEP",
        aggregate_id="policy-1",
        state=JobState.RUNNING,
        attempts=1,
        max_attempts=3,
    )


class FakeRetentionRepository:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.candidates = [
            RetentionCandidate("project", "active-1", "ACTIVE", legal_hold=False),
            RetentionCandidate("document", "held-1", "ARCHIVED", legal_hold=True),
            RetentionCandidate("document", "archived-1", "ARCHIVED", legal_hold=False),
            RetentionCandidate("document", "published-1", "PUBLISHED", legal_hold=False),
        ]

    async def list_candidates(self, policy_id: str) -> list[RetentionCandidate]:
        assert policy_id == "policy-1"
        return self.candidates

    async def delete_candidate(self, candidate: RetentionCandidate) -> None:
        self.deleted.append(candidate.resource_id)


@pytest.mark.asyncio
async def test_retention_sweep_defaults_to_dry_run() -> None:
    repo = FakeRetentionRepository()
    handler = RetentionSweepHandler(repo)

    result = await handler(retention_job())

    assert result.dry_run is True
    assert result.eligible_ids == ("archived-1",)
    assert repo.deleted == []


@pytest.mark.asyncio
async def test_retention_sweep_never_deletes_active_or_legal_hold() -> None:
    repo = FakeRetentionRepository()
    handler = RetentionSweepHandler(repo, dry_run=False)

    result = await handler(retention_job())

    assert result.deleted_ids == ("archived-1",)
    assert "active-1" not in repo.deleted
    assert "held-1" not in repo.deleted
    assert "published-1" not in repo.deleted
