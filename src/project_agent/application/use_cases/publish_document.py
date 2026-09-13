from __future__ import annotations

from uuid import UUID

from project_agent.application.ports.document_repository import (
    DocumentAuditRecord,
    DocumentVersionRecord,
    DocumentWorkflowRepository,
)
from project_agent.application.ports.knowledge import (
    IngestionState,
    KnowledgeIngestionPort,
    KnowledgeIngestionRequest,
)
from project_agent.application.use_cases.review_document import DocumentPermissionDenied
from project_agent.application.use_cases.upload_document import DocumentActor
from project_agent.domain.enums import DocumentLifecycleStatus


class DocumentPublishFailed(RuntimeError):
    pass


class DocumentPublishPending(RuntimeError):
    def __init__(self, ingestion_job_id: str) -> None:
        self.ingestion_job_id = ingestion_job_id
        super().__init__(ingestion_job_id)


class PublishDocumentUseCase:
    def __init__(
        self,
        repository: DocumentWorkflowRepository,
        knowledge: KnowledgeIngestionPort,
    ) -> None:
        self._repository = repository
        self._knowledge = knowledge

    async def execute(self, version_id: UUID, actor: DocumentActor) -> DocumentVersionRecord:
        if "publish_document" not in actor.permissions:
            raise DocumentPermissionDenied("publish_document permission is required")

        current = await self._repository.get_version(version_id)
        if current.lifecycle_status is not DocumentLifecycleStatus.APPROVED:
            raise ValueError("only APPROVED documents can be published")

        knowledge_space_id = await self._repository.knowledge_space_id(current.project_id)
        receipt = await self._knowledge.ingest(
            KnowledgeIngestionRequest(
                project_id=str(current.project_id),
                knowledge_space_id=knowledge_space_id,
                document_version_id=str(current.version_id),
                object_key=current.source_uri,
                metadata={
                    "filename": current.title,
                    "document_category": current.document_category,
                    "version_label": current.version_label,
                    "authority_level": current.authority_level,
                },
            )
        )
        await self._repository.add_audit(
            DocumentAuditRecord(
                action="document_publication_submitted",
                project_id=current.project_id,
                version_id=current.version_id,
                user_id=actor.user_id,
                details={"ingestion_job_id": receipt.ingestion_job_id},
            )
        )

        return await self._finalize(
            current,
            receipt.ingestion_job_id,
            actor,
        )

    async def finalize(
        self,
        version_id: UUID,
        ingestion_job_id: str,
        actor: DocumentActor,
    ) -> DocumentVersionRecord:
        if "publish_document" not in actor.permissions:
            raise DocumentPermissionDenied("publish_document permission is required")
        current = await self._repository.get_version(version_id)
        if current.lifecycle_status is not DocumentLifecycleStatus.APPROVED:
            raise ValueError("only APPROVED documents can complete publication")
        return await self._finalize(current, ingestion_job_id, actor)

    async def _finalize(
        self,
        current: DocumentVersionRecord,
        ingestion_job_id: str,
        actor: DocumentActor,
    ) -> DocumentVersionRecord:
        status = await self._knowledge.get_ingestion_status(ingestion_job_id)
        if status.state is IngestionState.FAILED:
            await self._repository.add_audit(
                DocumentAuditRecord(
                    action="document_publication_failed",
                    project_id=current.project_id,
                    version_id=current.version_id,
                    user_id=actor.user_id,
                    outcome="failed",
                    details={"error_code": status.error_code},
                )
            )
            # The new version remains APPROVED. The old PUBLISHED version is untouched.
            raise DocumentPublishFailed(status.error_code or "knowledge ingestion failed")
        if status.state is not IngestionState.SUCCEEDED:
            raise DocumentPublishPending(ingestion_job_id)

        published = await self._repository.complete_publication(
            current.version_id,
            supersedes_version_id=current.supersedes_version_id,
        )
        await self._repository.add_audit(
            DocumentAuditRecord(
                action="document_published",
                project_id=current.project_id,
                version_id=current.version_id,
                user_id=actor.user_id,
                details={
                    "supersedes_version_id": (
                        str(current.supersedes_version_id)
                        if current.supersedes_version_id
                        else None
                    )
                },
            )
        )
        return published
