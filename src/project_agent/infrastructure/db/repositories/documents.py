from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.ports.document_repository import (
    CreateDocumentDraft,
    DocumentAuditRecord,
    DocumentVersionRecord,
)
from project_agent.domain.documents import transition_document_status
from project_agent.domain.enums import DocumentLifecycleStatus
from project_agent.infrastructure.db.models.schema import (
    AuditLogModel,
    DocumentModel,
    DocumentVersionModel,
    ProjectKnowledgeSpaceModel,
)


class SqlAlchemyDocumentWorkflowRepository:
    """PostgreSQL-backed persistence for the Task 6 document workflow.

    The caller owns the AsyncSession transaction. ``complete_publication`` locks
    both versions before switching current authority, so the old PUBLISHED
    version is not superseded until the new version is ready.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_draft(self, draft: CreateDocumentDraft) -> DocumentVersionRecord:
        if draft.document_id is None:
            document = DocumentModel(
                id=uuid4(),
                company_id=draft.company_id,
                project_id=draft.project_id,
                document_category=draft.document_category,
                title=draft.title,
                owner_user_id=draft.owner_user_id,
            )
            self._session.add(document)
            await self._session.flush()
        else:
            existing_document = await self._session.get(DocumentModel, draft.document_id)
            if existing_document is None:
                raise LookupError(f"document {draft.document_id} does not exist")
            document = existing_document
            if document.project_id != draft.project_id:
                raise ValueError("document cannot move across projects")
            if document.document_category != draft.document_category:
                raise ValueError("new version cannot change document category")

        max_version_stmt = select(func.max(DocumentVersionModel.version_no)).where(
            DocumentVersionModel.document_id == document.id
        )
        max_version = (await self._session.execute(max_version_stmt)).scalar_one_or_none()
        version = DocumentVersionModel(
            id=uuid4(),
            document_id=document.id,
            version_no=int(max_version or 0) + 1,
            version_label=draft.version_label,
            authority_level=draft.authority_level,
            lifecycle_status=DocumentLifecycleStatus.DRAFT.value,
            effective_from=draft.effective_from,
            effective_to=draft.effective_to,
            supersedes_version_id=draft.supersedes_version_id,
            source_uri=draft.source_uri,
            content_hash=draft.content_hash,
            created_by=draft.created_by,
        )
        self._session.add(version)
        await self._session.flush()
        return self._to_record(document, version)

    async def get_version(self, version_id: UUID) -> DocumentVersionRecord:
        document, version = await self._load_version(version_id)
        return self._to_record(document, version)

    async def transition(
        self,
        version_id: UUID,
        *,
        expected: DocumentLifecycleStatus,
        target: DocumentLifecycleStatus,
    ) -> DocumentVersionRecord:
        document, version = await self._load_version(version_id, for_update=True)
        current = DocumentLifecycleStatus(version.lifecycle_status)
        if current is not expected:
            raise ValueError(f"expected {expected}, got {current}")
        transition_document_status(current, target)
        version.lifecycle_status = target.value
        await self._session.flush()
        return self._to_record(document, version)

    async def complete_publication(
        self,
        version_id: UUID,
        *,
        supersedes_version_id: UUID | None,
    ) -> DocumentVersionRecord:
        document, version = await self._load_version(version_id, for_update=True)
        current = DocumentLifecycleStatus(version.lifecycle_status)
        if current is not DocumentLifecycleStatus.APPROVED:
            raise ValueError("only APPROVED version can complete publication")

        old_version: DocumentVersionModel | None = None
        if supersedes_version_id is not None:
            old_document, old_version = await self._load_version(
                supersedes_version_id,
                for_update=True,
            )
            if old_document.id != document.id:
                raise ValueError("superseded version must belong to the same document")
            if DocumentLifecycleStatus(old_version.lifecycle_status) is not (
                DocumentLifecycleStatus.PUBLISHED
            ):
                raise ValueError("superseded version must still be PUBLISHED")

        # Both rows are locked before either status changes.
        version.lifecycle_status = DocumentLifecycleStatus.PUBLISHED.value
        version.published_at = datetime.now(UTC)
        if old_version is not None:
            old_version.lifecycle_status = DocumentLifecycleStatus.SUPERSEDED.value
        await self._session.flush()
        return self._to_record(document, version)

    async def add_audit(self, audit: DocumentAuditRecord) -> None:
        self._session.add(
            AuditLogModel(
                project_id=audit.project_id,
                user_id=audit.user_id,
                action=audit.action,
                resource_type="document_version",
                resource_id=str(audit.version_id),
                outcome=audit.outcome,
                details_json=audit.details,
            )
        )
        await self._session.flush()

    async def knowledge_space_id(self, project_id: UUID) -> str:
        stmt = select(ProjectKnowledgeSpaceModel.external_space_id).where(
            ProjectKnowledgeSpaceModel.project_id == project_id,
            ProjectKnowledgeSpaceModel.provider == "ragflow",
            ProjectKnowledgeSpaceModel.status == "active",
        )
        value = (await self._session.execute(stmt)).scalar_one_or_none()
        if value is None:
            raise LookupError(f"project {project_id} has no active RAGFlow knowledge space")
        return str(value)

    async def _load_version(
        self,
        version_id: UUID,
        *,
        for_update: bool = False,
    ) -> tuple[DocumentModel, DocumentVersionModel]:
        stmt = (
            select(DocumentModel, DocumentVersionModel)
            .join(DocumentVersionModel, DocumentVersionModel.document_id == DocumentModel.id)
            .where(DocumentVersionModel.id == version_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            raise LookupError(f"document version {version_id} does not exist")
        return row[0], row[1]

    @staticmethod
    def _to_record(
        document: DocumentModel,
        version: DocumentVersionModel,
    ) -> DocumentVersionRecord:
        if version.source_uri is None or version.content_hash is None:
            raise ValueError("document version source metadata is incomplete")
        return DocumentVersionRecord(
            company_id=document.company_id,
            project_id=document.project_id,
            document_id=document.id,
            version_id=version.id,
            document_category=document.document_category,
            title=document.title,
            version_no=version.version_no,
            version_label=version.version_label,
            authority_level=version.authority_level,
            lifecycle_status=DocumentLifecycleStatus(version.lifecycle_status),
            owner_user_id=document.owner_user_id,
            created_by=version.created_by,
            source_uri=version.source_uri,
            content_hash=version.content_hash,
            effective_from=version.effective_from,
            effective_to=version.effective_to,
            supersedes_version_id=version.supersedes_version_id,
            published_at=version.published_at,
        )
