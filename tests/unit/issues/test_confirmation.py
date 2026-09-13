from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from project_agent.application.services.issue_confirmation import (
    ConfirmationPayloadMismatch,
    IssueConfirmationService,
)
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.issues import ConfirmationAction, ToolConfirmationStatus
from tests.fakes.issue_workflow import FakeIssueWorkflowRepository


@pytest.mark.asyncio
async def test_confirmation_binds_exact_payload_hash() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    draft = await drafts.create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=uuid4(), text="ERR-IMPORT-004 failed"
    )
    service = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)
    request = await service.prepare(draft.id)

    receipt = await service.record_decision(
        draft_id=draft.id,
        actor_id=draft.created_by,
        action=ConfirmationAction.CONFIRM,
        request_payload_hash=request.request_payload_hash,
    )

    assert receipt.status is ToolConfirmationStatus.CONFIRMED
    assert receipt.request_payload_hash == request.request_payload_hash
    assert receipt.expires_at == draft.created_at + timedelta(minutes=15)


@pytest.mark.asyncio
async def test_confirmation_rejects_stale_or_tampered_payload_hash() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    draft = await drafts.create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=uuid4(), text="upload failed"
    )
    service = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)

    with pytest.raises(ConfirmationPayloadMismatch):
        await service.record_decision(
            draft_id=draft.id,
            actor_id=draft.created_by,
            action=ConfirmationAction.CONFIRM,
            request_payload_hash="0" * 64,
        )

    assert repo.confirmations == {}
