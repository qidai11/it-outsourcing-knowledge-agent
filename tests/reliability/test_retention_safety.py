from __future__ import annotations

import pytest

from project_agent.workers.retention import (
    RetentionCandidate,
    RetentionSweepHandler,
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

    result = await handler("policy-1")

    assert result.dry_run is True
    assert result.eligible_ids == ("archived-1",)
    assert repo.deleted == []


@pytest.mark.asyncio
async def test_retention_sweep_never_deletes_active_or_legal_hold() -> None:
    repo = FakeRetentionRepository()
    handler = RetentionSweepHandler(repo, dry_run=False)

    result = await handler("policy-1")

    assert result.deleted_ids == ("archived-1",)
    assert "active-1" not in repo.deleted
    assert "held-1" not in repo.deleted
    assert "published-1" not in repo.deleted
