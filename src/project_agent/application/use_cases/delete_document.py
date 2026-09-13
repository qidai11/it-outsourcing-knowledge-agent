from __future__ import annotations

from uuid import UUID

from project_agent.application.ports.document_repository import (
    DocumentAuditRecord,
    DocumentVersionRecord,
    DocumentWorkflowRepository,
)
from project_agent.application.ports.knowledge import (
    DeleteKnowledgeDocumentRequest,
    KnowledgeAdminPort,
)
from project_agent.application.ports.transaction import TransactionCommitPort
from project_agent.application.use_cases.review_document import DocumentPermissionDenied
from project_agent.application.use_cases.upload_document import DocumentActor
from project_agent.domain.enums import DocumentLifecycleStatus


class DeleteDocumentUseCase:
    def __init__(
        self,
        repository: DocumentWorkflowRepository,
        knowledge: KnowledgeAdminPort,
        *,
        commit_barrier: TransactionCommitPort | None = None,
    ) -> None:
        self._repository = repository
        self._knowledge = knowledge
        self._commit_barrier = commit_barrier

    async def execute(self, version_id: UUID, actor: DocumentActor) -> DocumentVersionRecord:
        if "archive_document" not in actor.permissions:
            raise DocumentPermissionDenied("archive_document permission is required")
        current = await self._repository.get_version(version_id)

        # Governance first: once DELETE_PENDING is persisted the version is no longer
        # eligible for online retrieval, even if provider cleanup subsequently fails.
        pending = await self._repository.transition(
            version_id,
            expected=current.lifecycle_status,
            target=DocumentLifecycleStatus.DELETE_PENDING,
        )
        await self._repository.add_audit(
            DocumentAuditRecord(
                action="document_delete_pending",
                project_id=current.project_id,
                version_id=version_id,
                user_id=actor.user_id,
            )
        )

        if self._commit_barrier is not None:
            await self._commit_barrier.commit()

        knowledge_space_id = await self._repository.knowledge_space_id(current.project_id)
        await self._knowledge.delete_document(
            DeleteKnowledgeDocumentRequest(
                project_id=str(current.project_id),
                document_version_id=str(current.version_id),
                knowledge_space_id=knowledge_space_id,
            )
        )
        return pending
