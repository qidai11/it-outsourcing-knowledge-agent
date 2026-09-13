from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.issue_creation import (
    IssueCreationDenied,
    IssueCreationService,
)
from project_agent.application.services.issue_drafts import IssueDraftService
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.issue_workflow import FakeIdempotencyStore, FakeIssueWorkflowRepository
from tests.fakes.job_queue import FakeJobQueue
from tests.fakes.project_tracker import SandboxProjectTrackerAdapter


@pytest.mark.asyncio
async def test_reconcile_without_prior_idempotency_barrier_cannot_create() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    draft = await IssueDraftService(repo).create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=uuid4(), text="ERR-IMPORT-004 failed"
    )
    tracker = SandboxProjectTrackerAdapter()
    service = IssueCreationService(
        workflow_repo=repo,
        idempotency=FakeIdempotencyStore(clock=lambda: now),
        tracker=tracker,
        authorization=AuthorizationService(FakeProjectAuthorizationRepository(), clock=lambda: now),
        job_queue=FakeJobQueue(),
        clock=lambda: now,
    )

    with pytest.raises(IssueCreationDenied, match="idempotency barrier"):
        await service.reconcile(draft.id)
    assert tracker.create_side_effect_count == 0
