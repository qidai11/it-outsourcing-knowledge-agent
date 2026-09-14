from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from tests.fakes.issue_workflow import FakeIssueWorkflowRepository

from project_agent.application.services.issue_confirmation import IssueConfirmationService
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.issues import ConfirmationAction, IssueDraftStatus


@pytest.mark.asyncio
async def test_cancel_confirmation_marks_draft_cancelled_without_tool_side_effect() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    draft = await drafts.create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=uuid4(), text="upload failed"
    )
    confirmations = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)
    prompt = await confirmations.prepare(draft.id)
    await confirmations.record_decision(
        draft_id=draft.id,
        actor_id=draft.created_by,
        action=ConfirmationAction.CANCEL,
        request_payload_hash=prompt.request_payload_hash,
    )
    updated = await repo.get_draft(draft.id)
    assert updated.status is IssueDraftStatus.CANCELLED
