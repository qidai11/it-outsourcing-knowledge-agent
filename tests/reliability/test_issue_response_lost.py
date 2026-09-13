from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from project_agent.application.services.authorization import (
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.application.services.issue_confirmation import IssueConfirmationService
from project_agent.application.services.issue_creation import (
    IssueCreationService,
    IssueCreationStatus,
)
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.enums import ProjectRole
from project_agent.domain.issues import ConfirmationAction
from project_agent.workers.handlers import RECONCILE_ISSUE_CREATE
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.issue_workflow import FakeIdempotencyStore, FakeIssueWorkflowRepository
from tests.fakes.job_queue import FakeJobQueue
from tests.fakes.project_tracker import ResponseLostProjectTracker


@pytest.mark.asyncio
async def test_response_lost_is_reconciled_without_duplicate_issue() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    project_id, user_id = uuid4(), uuid4()
    auth_repo = FakeProjectAuthorizationRepository()
    auth_repo.memberships[(user_id, project_id)] = MembershipAccessRecord(
        company_id=uuid4(), client_id=uuid4(), project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA", role=ProjectRole.DEVELOPER,
        valid_from=now, valid_to=None,
    )
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    draft = await drafts.create_from_text(
        run_id=uuid4(), project_id=project_id, created_by=user_id, text="ERR-IMPORT-004 failed"
    )
    confirmations = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)
    prompt = await confirmations.prepare(draft.id)
    receipt = await confirmations.record_decision(
        draft_id=draft.id, actor_id=user_id, action=ConfirmationAction.CONFIRM,
        request_payload_hash=prompt.request_payload_hash,
    )
    tracker = ResponseLostProjectTracker()
    queue = FakeJobQueue()
    service = IssueCreationService(
        workflow_repo=repo,
        idempotency=FakeIdempotencyStore(clock=lambda: now),
        tracker=tracker,
        authorization=AuthorizationService(auth_repo, clock=lambda: now),
        job_queue=queue,
        clock=lambda: now,
    )

    uncertain = await service.execute(
        draft_id=draft.id, confirmation_id=receipt.id, actor_id=user_id
    )
    assert uncertain.status is IssueCreationStatus.PENDING_RECONCILIATION
    assert tracker.create_side_effect_count == 1
    queued = list(queue._jobs.values())
    assert len(queued) == 1
    assert queued[0].job_type == RECONCILE_ISSUE_CREATE
    assert queued[0].aggregate_id == str(draft.id)

    reconciled = await service.reconcile(draft.id)
    assert reconciled.status is IssueCreationStatus.RECONCILED
    assert tracker.create_side_effect_count == 1
    assert reconciled.issue_key is not None
