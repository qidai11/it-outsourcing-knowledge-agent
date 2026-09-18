from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

from project_agent.application.services.authorization import AuthorizedProjectContext
from project_agent.application.services.evidence_governance import EvidenceGovernanceRepository
from project_agent.domain.enums import DocumentCategory, DocumentLifecycleStatus


class IssueEvidenceSelector:
    ALLOWED_CATEGORIES = frozenset(
        {
            DocumentCategory.REQUIREMENT_BASELINE,
            DocumentCategory.APPROVED_TEST_SPEC,
        }
    )

    def __init__(
        self,
        repository: EvidenceGovernanceRepository,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._repository = repository
        self._today = today or date.today

    async def select_document_version_ids(
        self,
        *,
        project_id: UUID,
        context: AuthorizedProjectContext,
    ) -> tuple[UUID, ...]:
        allowed = tuple(context.scope.allowed_document_version_ids or ())
        if not allowed:
            return ()

        metadata = await self._repository.get_document_evidence_metadata(
            document_version_ids=allowed
        )
        today = self._today()
        selected: list[UUID] = []
        for version_id in allowed:
            item = metadata.get(version_id)
            if item is None or item.project_id != project_id:
                continue
            if item.document_category not in self.ALLOWED_CATEGORIES:
                continue
            if item.lifecycle_status is not DocumentLifecycleStatus.PUBLISHED:
                continue
            if not item.is_current:
                continue
            if item.effective_from is not None and item.effective_from > today:
                continue
            if item.effective_to is not None and item.effective_to < today:
                continue
            selected.append(version_id)

        return tuple(sorted(set(selected), key=str))
