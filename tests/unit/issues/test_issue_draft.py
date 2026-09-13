from __future__ import annotations

from uuid import uuid4

import pytest

from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.application.services.issue_candidates import (
    IssueCandidate,
    IssueCandidateQuery,
    IssueCandidateResult,
)
from project_agent.domain.issues import IssueDraftStatus
from tests.fakes.issue_workflow import FakeIssueWorkflowRepository


@pytest.mark.asyncio
async def test_create_draft_persists_possible_duplicate_links() -> None:
    repo = FakeIssueWorkflowRepository()
    service = IssueDraftService(repo)
    run_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    candidates = IssueCandidateResult(
        query=IssueCandidateQuery(
            project_id=str(project_id),
            title="CSV import fails",
            description="ERR-IMPORT-004",
            error_code="ERR-IMPORT-004",
        ),
        possible_duplicates=(
            IssueCandidate(
                project_id=str(project_id),
                issue_key="ALPHA-101",
                title="CSV import fails",
                description="encoding",
                status="OPEN",
                issue_type="bug",
                priority="high",
                score=1010.0,
                reasons=("exact_error_code",),
            ),
        ),
    )

    draft = await service.create_from_text(
        run_id=run_id,
        project_id=project_id,
        created_by=user_id,
        text="模块: import\nCSV import fails with ERR-IMPORT-004 in UAT",
        candidates=candidates,
    )

    assert draft.status is IssueDraftStatus.DRAFT
    assert draft.issue_type == "bug"
    assert draft.module == "import"
    assert draft.description.startswith("模块: import")
    links = await repo.list_candidate_links(draft.id)
    assert [item.issue_key for item in links] == ["ALPHA-101"]
    assert links[0].reasons == ("exact_error_code",)


@pytest.mark.asyncio
async def test_request_id_is_draft_uuid_and_payload_is_stable() -> None:
    repo = FakeIssueWorkflowRepository()
    service = IssueDraftService(repo)
    draft = await service.create_from_text(
        run_id=uuid4(),
        project_id=uuid4(),
        created_by=uuid4(),
        text="ERR-IMPORT-004 upload failed",
    )

    first = service.build_create_request(draft)
    second = service.build_create_request(draft)

    assert first.request_id == str(draft.id)
    assert first == second
    assert service.payload_hash(first) == service.payload_hash(second)
