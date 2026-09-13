from __future__ import annotations

import pytest

from project_agent.application.ports.project_tracker import (
    CreateIssueRequest,
    ProjectTrackerPort,
    SearchIssuesRequest,
)
from tests.fakes.project_tracker import SandboxProjectTrackerAdapter


@pytest.mark.asyncio
async def test_sandbox_tracker_returns_project_scoped_canonical_issues() -> None:
    tracker = SandboxProjectTrackerAdapter()
    assert isinstance(tracker, ProjectTrackerPort)

    tracker.seed_issue(
        project_id="project-alpha",
        issue_key="ALPHA-101",
        title="Import failed",
        description="ERR-IMPORT-004 while importing",
        status="OPEN",
        module="import",
        error_code="ERR-IMPORT-004",
    )
    tracker.seed_issue(
        project_id="project-beta",
        issue_key="BETA-101",
        title="Import failed",
        description="ERR-IMPORT-004 while importing",
        status="OPEN",
        module="import",
        error_code="ERR-IMPORT-004",
    )

    issues = await tracker.search_issues(
        SearchIssuesRequest(project_id="project-alpha", error_code="ERR-IMPORT-004")
    )

    assert [issue.issue_key for issue in issues] == ["ALPHA-101"]
    assert all(issue.project_id == "project-alpha" for issue in issues)
    assert all(not hasattr(issue, "sandbox_issue_id") for issue in issues)


@pytest.mark.asyncio
async def test_sandbox_tracker_create_is_idempotent_by_request_id() -> None:
    tracker = SandboxProjectTrackerAdapter()
    request = CreateIssueRequest(
        project_id="project-alpha",
        request_id="req-001",
        title="Import fails",
        description="ERR-IMPORT-004",
        issue_type="bug",
        priority="high",
        reporter_id="user-1",
    )

    first = await tracker.create_issue(request)
    second = await tracker.create_issue(request)

    assert second.issue_key == first.issue_key
    assert tracker.create_side_effect_count == 1
    assert await tracker.get_issue_by_request_id("project-alpha", "req-001") == first
