from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.issue_workflow import FakeIdempotencyStore, FakeIssueWorkflowRepository
from tests.fakes.job_queue import FakeJobQueue
from tests.fakes.project_tracker import SandboxProjectTrackerAdapter

from project_agent.application.services.authorization import (
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.application.services.issue_creation import (
    IssueCreationDenied,
    IssueCreationService,
)
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.enums import ProjectRole


@pytest.mark.asyncio
async def test_no_confirmation_means_zero_create_side_effects() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    project_id = uuid4()
    user_id = uuid4()
    auth_repo = FakeProjectAuthorizationRepository()
    auth_repo.memberships[(user_id, project_id)] = MembershipAccessRecord(
        company_id=uuid4(), client_id=uuid4(), project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA", role=ProjectRole.DEVELOPER,
        valid_from=now, valid_to=None,
    )
    workflow_repo = FakeIssueWorkflowRepository(clock=lambda: now)
    draft = await IssueDraftService(workflow_repo).create_from_text(
        run_id=uuid4(), project_id=project_id, created_by=user_id, text="ERR-IMPORT-004 failed"
    )
    tracker = SandboxProjectTrackerAdapter()
    service = IssueCreationService(
        workflow_repo=workflow_repo,
        idempotency=FakeIdempotencyStore(clock=lambda: now),
        tracker=tracker,
        authorization=AuthorizationService(auth_repo, clock=lambda: now),
        job_queue=FakeJobQueue(),
        clock=lambda: now,
    )

    with pytest.raises(IssueCreationDenied, match="confirmation"):
        await service.execute(draft_id=draft.id, confirmation_id=uuid4(), actor_id=user_id)

    assert tracker.create_side_effect_count == 0
