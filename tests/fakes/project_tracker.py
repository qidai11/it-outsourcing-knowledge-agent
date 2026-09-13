from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from project_agent.application.ports.project_tracker import (
    CreatedIssue,
    CreateIssueRequest,
    ProjectIssue,
    SearchIssuesRequest,
)


@dataclass(slots=True)
class _SeededIssue:
    issue: ProjectIssue


class SandboxProjectTrackerAdapter:
    """In-memory contract substitute; Task 12 adds the PostgreSQL-backed adapter."""

    def __init__(self) -> None:
        self._issues: list[_SeededIssue] = []
        self._created_by_request: dict[tuple[str, str], CreatedIssue] = {}
        self.create_side_effect_count = 0
        self.search_requests: list[SearchIssuesRequest] = []

    def seed_issue(
        self,
        *,
        project_id: str,
        issue_key: str,
        title: str,
        description: str,
        status: str,
        module: str | None = None,
        error_code: str | None = None,
        issue_type: str = "bug",
        priority: str = "medium",
        environment: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self._issues.append(
            _SeededIssue(
                issue=ProjectIssue(
                    project_id=project_id,
                    issue_key=issue_key,
                    title=title,
                    description=description,
                    status=status,
                    issue_type=issue_type,
                    priority=priority,
                    module=module,
                    error_code=error_code,
                    environment=environment,
                    created_at=created_at,
                )
            )
        )

    async def search_issues(self, request: SearchIssuesRequest) -> list[ProjectIssue]:
        self.search_requests.append(request)
        issues = [
            item.issue
            for item in self._issues
            if item.issue.project_id == request.project_id
        ]
        if request.error_code is not None:
            issues = [issue for issue in issues if issue.error_code == request.error_code]
        if request.module is not None:
            issues = [issue for issue in issues if issue.module == request.module]
        if request.statuses:
            statuses = set(request.statuses)
            issues = [issue for issue in issues if issue.status in statuses]
        if request.query:
            query = request.query.casefold()
            issues = [
                issue
                for issue in issues
                if query in issue.title.casefold() or query in issue.description.casefold()
            ]
        return issues[: request.limit]

    async def create_issue(self, request: CreateIssueRequest) -> CreatedIssue:
        key = (request.project_id, request.request_id)
        existing = self._created_by_request.get(key)
        if existing is not None:
            return existing

        self.create_side_effect_count += 1
        prefix = "ALPHA" if "alpha" in request.project_id.casefold() else "BETA"
        created = CreatedIssue(
            project_id=request.project_id,
            request_id=request.request_id,
            issue_key=f"{prefix}-{1000 + self.create_side_effect_count}",
            status="OPEN",
        )
        self._created_by_request[key] = created
        self.seed_issue(
            project_id=request.project_id,
            issue_key=created.issue_key,
            title=request.title,
            description=request.description,
            status=created.status,
            module=request.module,
            error_code=request.error_code,
            issue_type=request.issue_type,
            priority=request.priority,
            environment=request.environment,
        )
        return created

    async def get_issue_by_request_id(
        self,
        project_id: str,
        request_id: str,
    ) -> CreatedIssue | None:
        return self._created_by_request.get((project_id, request_id))


class ResponseLostProjectTracker(SandboxProjectTrackerAdapter):
    """Creates the issue once, then simulates a lost provider response."""

    def __init__(self) -> None:
        super().__init__()
        self._lose_next_response = True

    async def create_issue(self, request: CreateIssueRequest) -> CreatedIssue:
        created = await super().create_issue(request)
        if self._lose_next_response:
            self._lose_next_response = False
            raise TimeoutError("simulated response loss after provider commit")
        return created
