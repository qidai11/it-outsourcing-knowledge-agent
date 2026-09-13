from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from project_agent.application.ports.project_tracker import ProjectTrackerPort, SearchIssuesRequest
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.domain.identifiers import IdentifierType


class IssueCandidateAction(StrEnum):
    VIEW_EXISTING = "view_existing_issue"
    LINK_EXISTING = "link_existing_issue"
    CONTINUE_CREATE = "continue_create"
    CANCEL = "cancel"


class IssueCandidateQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    error_code: str | None = None
    module: str | None = None
    statuses: tuple[str, ...] = ()
    semantic_scores: dict[str, float] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1, le=20)


class IssueCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    score: float
    reasons: tuple[str, ...]
    semantic_score: float | None = None


class IssueCandidateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: IssueCandidateQuery
    possible_duplicates: tuple[IssueCandidate, ...]
    user_options: tuple[IssueCandidateAction, ...] = (
        IssueCandidateAction.VIEW_EXISTING,
        IssueCandidateAction.LINK_EXISTING,
        IssueCandidateAction.CONTINUE_CREATE,
        IssueCandidateAction.CANCEL,
    )


_LATIN_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_MODULE_LABEL = re.compile(r"(?:模块|module)\s*[:：=]\s*([A-Za-z0-9_.-]+)", re.IGNORECASE)


class IssueCandidateService:
    """Deterministic possible-duplicate ranking.

    Scores are presentation hints only. This service never returns an
    authoritative duplicate decision and never calls ``create_issue``.
    """

    _STATUS_SCORE = {
        "OPEN": 8.0,
        "REOPENED": 8.0,
        "IN_PROGRESS": 7.0,
        "RESOLVED": 3.0,
        "CLOSED": 0.0,
    }

    def __init__(self, *, tracker: ProjectTrackerPort, extractor: IdentifierExtractor) -> None:
        self._tracker = tracker
        self._extractor = extractor

    async def find_candidates_from_text(
        self,
        *,
        project_id: str,
        text: str,
        limit: int = 5,
        semantic_scores: dict[str, float] | None = None,
    ) -> IssueCandidateResult:
        stripped = text.strip()
        if not stripped:
            raise ValueError("issue text cannot be blank")
        error_code = next(
            (
                item.normalized_value
                for item in self._extractor.extract(stripped)
                if item.identifier_type is IdentifierType.ERROR_CODE
            ),
            None,
        )
        module_match = _MODULE_LABEL.search(stripped)
        module = module_match.group(1) if module_match else None
        return await self.find_candidates(
            IssueCandidateQuery(
                project_id=project_id,
                title=stripped,
                description=stripped,
                error_code=error_code,
                module=module,
                semantic_scores=semantic_scores or {},
                limit=limit,
            )
        )

    async def find_candidates(self, query: IssueCandidateQuery) -> IssueCandidateResult:
        # Broad same-project pool first. Ranking then combines all deterministic signals.
        pool = await self._tracker.search_issues(
            SearchIssuesRequest(project_id=query.project_id, limit=100)
        )
        ranked: list[tuple[tuple[float, ...], IssueCandidate]] = []
        query_title = self._tokens(query.title)
        query_description = self._tokens(query.description)
        requested_statuses = {status.upper() for status in query.statuses}

        for issue in pool:
            if issue.project_id != query.project_id:
                # Defense in depth against a broken provider/adapter.
                continue
            reasons: list[str] = []
            matched = False
            exact_error = 0.0
            module_match = 0.0

            if (
                query.error_code
                and issue.error_code
                and issue.error_code.upper() == query.error_code.upper()
            ):
                exact_error = 1.0
                reasons.append("exact_error_code")
                matched = True

            if (
                query.module
                and issue.module
                and issue.module.casefold() == query.module.casefold()
            ):
                module_match = 1.0
                reasons.append("module_match")
                matched = True

            title_overlap = self._overlap(query_title, self._tokens(issue.title))
            if title_overlap > 0:
                reasons.append("title_keyword")
                matched = True

            description_overlap = self._overlap(
                query_description,
                self._tokens(issue.description),
            )
            if description_overlap > 0:
                reasons.append("description_keyword")
                matched = True

            status_score = self._STATUS_SCORE.get(issue.status.upper(), 0.0)
            if requested_statuses and issue.status.upper() in requested_statuses:
                status_score += 10.0
                reasons.append("requested_status")
                matched = True
            reasons.append(f"status:{issue.status.upper()}")

            semantic_score = query.semantic_scores.get(issue.issue_key)
            bounded_semantic = 0.0
            if semantic_score is not None:
                bounded_semantic = max(0.0, min(float(semantic_score), 1.0))
                if bounded_semantic > 0:
                    reasons.append("semantic_score")
                    matched = True
                semantic_score = bounded_semantic

            if not matched:
                continue
            display_score = (
                exact_error * 1000.0
                + module_match * 100.0
                + title_overlap * 20.0
                + description_overlap * 10.0
                + status_score
                + bounded_semantic * 5.0
            )
            candidate = IssueCandidate(
                project_id=issue.project_id,
                issue_key=issue.issue_key,
                title=issue.title,
                description=issue.description,
                status=issue.status,
                issue_type=issue.issue_type,
                priority=issue.priority,
                module=issue.module,
                error_code=issue.error_code,
                environment=issue.environment,
                created_at=issue.created_at,
                score=round(display_score, 6),
                reasons=tuple(reasons),
                semantic_score=semantic_score,
            )
            # Lexicographic key enforces the V3.2 precedence exactly.
            rank_key = (
                exact_error,
                module_match,
                title_overlap,
                description_overlap,
                status_score,
                bounded_semantic,
                issue.created_at.timestamp() if issue.created_at is not None else 0.0,
            )
            ranked.append((rank_key, candidate))

        ranked.sort(
            key=lambda item: (
                tuple(-value for value in item[0]),
                item[1].issue_key,
            )
        )
        return IssueCandidateResult(
            query=query,
            possible_duplicates=tuple(item[1] for item in ranked[: query.limit]),
        )

    @staticmethod
    def _tokens(value: str) -> set[str]:
        result = {token.casefold() for token in _LATIN_TOKEN.findall(value) if len(token) > 1}
        for run in _CJK_RUN.findall(value):
            if len(run) == 1:
                result.add(run)
            else:
                result.update(run[index : index + 2] for index in range(len(run) - 1))
        return result

    @staticmethod
    def _overlap(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / max(1, min(len(left), len(right)))
