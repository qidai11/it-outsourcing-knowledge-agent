from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SearchIssuesRequest:
    project_id: str
    query: str | None = None
    error_code: str | None = None
    module: str | None = None
    statuses: tuple[str, ...] = ()
    limit: int = 20


@dataclass(frozen=True, slots=True)
class ProjectIssue:
    project_id: str
    issue_key: str
    title: str
    description: str
    status: str
    issue_type: str
    priority: str
    module: str | None = None
    error_code: str | None = None
    environment: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CreateIssueRequest:
    project_id: str
    request_id: str
    title: str
    description: str
    issue_type: str
    priority: str
    reporter_id: str
    module: str | None = None
    error_code: str | None = None
    environment: str | None = None


@dataclass(frozen=True, slots=True)
class CreatedIssue:
    project_id: str
    request_id: str
    issue_key: str
    status: str


@runtime_checkable
class ProjectTrackerPort(Protocol):
    async def search_issues(self, request: SearchIssuesRequest) -> list[ProjectIssue]: ...

    async def create_issue(self, request: CreateIssueRequest) -> CreatedIssue: ...

    async def get_issue_by_request_id(
        self,
        project_id: str,
        request_id: str,
    ) -> CreatedIssue | None: ...
