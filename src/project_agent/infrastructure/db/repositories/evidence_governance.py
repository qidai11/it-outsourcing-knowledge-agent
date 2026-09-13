from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.services.evidence_governance import DocumentEvidenceMetadata
from project_agent.domain.enums import (
    AuthorityLevel,
    DocumentCategory,
    DocumentLifecycleStatus,
)
from project_agent.infrastructure.db.models.schema import DocumentModel, DocumentVersionModel


class SqlAlchemyEvidenceGovernanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_document_evidence_metadata(
        self, *, document_version_ids: tuple[UUID, ...]
    ) -> dict[UUID, DocumentEvidenceMetadata]:
        if not document_version_ids:
            return {}
        stmt = (
            select(DocumentVersionModel, DocumentModel)
            .join(DocumentModel, DocumentModel.id == DocumentVersionModel.document_id)
            .where(DocumentVersionModel.id.in_(document_version_ids))
        )
        rows = (await self._session.execute(stmt)).all()
        document_ids = tuple({version.document_id for version, _document in rows})
        current_versions: dict[UUID, int] = {}
        if document_ids:
            current_stmt = (
                select(
                    DocumentVersionModel.document_id,
                    func.max(DocumentVersionModel.version_no),
                )
                .where(
                    DocumentVersionModel.document_id.in_(document_ids),
                    DocumentVersionModel.lifecycle_status
                    == DocumentLifecycleStatus.PUBLISHED.value,
                )
                .group_by(DocumentVersionModel.document_id)
            )
            current_versions = {
                document_id: int(version_no)
                for document_id, version_no in (await self._session.execute(current_stmt)).all()
            }

        result: dict[UUID, DocumentEvidenceMetadata] = {}
        for version, document in rows:
            result[version.id] = DocumentEvidenceMetadata(
                document_version_id=version.id,
                document_id=version.document_id,
                project_id=document.project_id,
                document_category=DocumentCategory(document.document_category),
                title=document.title,
                authority_level=AuthorityLevel(version.authority_level),
                lifecycle_status=DocumentLifecycleStatus(version.lifecycle_status),
                version_no=version.version_no,
                version_label=version.version_label,
                effective_from=version.effective_from,
                effective_to=version.effective_to,
                is_current=(
                    version.lifecycle_status == DocumentLifecycleStatus.PUBLISHED.value
                    and current_versions.get(version.document_id) == version.version_no
                ),
            )
        return result
