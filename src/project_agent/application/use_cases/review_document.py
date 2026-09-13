from __future__ import annotations

from uuid import UUID

from project_agent.application.ports.document_repository import (
    DocumentAuditRecord,
    DocumentVersionRecord,
    DocumentWorkflowRepository,
)
from project_agent.application.use_cases.upload_document import DocumentActor
from project_agent.domain.enums import DocumentLifecycleStatus


class DocumentPermissionDenied(PermissionError):
    pass


class SubmitDocumentReviewUseCase:
    def __init__(self, repository: DocumentWorkflowRepository) -> None:
        self._repository = repository

    async def execute(self, version_id: UUID, actor: DocumentActor) -> DocumentVersionRecord:
        current = await self._repository.get_version(version_id)
        if actor.user_id not in {current.created_by, current.owner_user_id} and (
            "submit_review" not in actor.permissions
        ):
            raise DocumentPermissionDenied("actor cannot submit this document for review")
        updated = await self._repository.transition(
            version_id,
            expected=DocumentLifecycleStatus.DRAFT,
            target=DocumentLifecycleStatus.UNDER_REVIEW,
        )
        await self._repository.add_audit(
            DocumentAuditRecord(
                action="document_submitted_for_review",
                project_id=current.project_id,
                version_id=version_id,
                user_id=actor.user_id,
            )
        )
        return updated


class ApproveDocumentUseCase:
    def __init__(self, repository: DocumentWorkflowRepository) -> None:
        self._repository = repository

    async def execute(self, version_id: UUID, actor: DocumentActor) -> DocumentVersionRecord:
        current = await self._repository.get_version(version_id)
        if current.owner_user_id is None or actor.user_id != current.owner_user_id:
            raise DocumentPermissionDenied("only the document owner can approve the document")
        updated = await self._repository.transition(
            version_id,
            expected=DocumentLifecycleStatus.UNDER_REVIEW,
            target=DocumentLifecycleStatus.APPROVED,
        )
        await self._repository.add_audit(
            DocumentAuditRecord(
                action="document_approved",
                project_id=current.project_id,
                version_id=version_id,
                user_id=actor.user_id,
            )
        )
        return updated
