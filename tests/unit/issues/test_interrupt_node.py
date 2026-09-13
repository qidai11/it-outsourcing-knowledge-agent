from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from project_agent.agent.nodes.confirm_issue_create import confirm_issue_create_node
from project_agent.application.services.issue_confirmation import IssueConfirmationService
from project_agent.application.services.issue_drafts import IssueDraftService
from tests.fakes.issue_workflow import FakeIssueWorkflowRepository


class Paused(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_interrupt_occurs_before_confirmation_write() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    user_id = uuid4()
    draft = await drafts.create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=user_id, text="ERR-IMPORT-004 failed"
    )
    confirmations = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)

    def pause(_value):
        raise Paused

    with pytest.raises(Paused):
        await confirm_issue_create_node(
            {
                "run_id": str(draft.run_id),
                "thread_id": str(uuid4()),
                "user_id": str(user_id),
                "project_id": str(draft.project_id),
                "issue_draft_id": str(draft.id),
            },
            confirmations=confirmations,
            interrupt_fn=pause,
        )

    assert repo.confirmations == {}
