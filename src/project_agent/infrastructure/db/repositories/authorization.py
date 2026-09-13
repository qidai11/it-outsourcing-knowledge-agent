from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.services.authorization import (
    DocumentAccessRecord,
    MembershipAccessRecord,
)
from project_agent.domain.enums import DocumentLifecycleStatus, ProjectLifecycleStatus, ProjectRole
from project_agent.infrastructure.db.models.schema import (
    DocumentModel,
    DocumentVersionModel,
    ProjectKnowledgeSpaceModel,
    ProjectMembershipModel,
    ProjectModel,
)


class SqlAlchemyProjectAuthorizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_membership(
        self, *, user_id: UUID, project_id: UUID, at: datetime
    ) -> MembershipAccessRecord | None:
        stmt = (
            select(ProjectMembershipModel, ProjectModel)
            .join(ProjectModel, ProjectModel.id == ProjectMembershipModel.project_id)
            .where(
                ProjectMembershipModel.user_id == user_id,
                ProjectMembershipModel.project_id == project_id,
                ProjectMembershipModel.valid_from <= at,
                or_(ProjectMembershipModel.valid_to.is_(None), ProjectMembershipModel.valid_to > at),
                ProjectModel.lifecycle_status.notin_(
                    [ProjectLifecycleStatus.DELETION_PENDING.value, ProjectLifecycleStatus.DELETED.value]
                ),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        membership, project = row
        return MembershipAccessRecord(
            company_id=project.company_id,
            client_id=project.client_id,
            project_id=project.id,
            project_code=project.code,
            role=ProjectRole(membership.role),
            valid_from=membership.valid_from,
            valid_to=membership.valid_to,
        )


    async def list_active_memberships_for_user(
        self, *, user_id: UUID, at: datetime
    ) -> tuple[MembershipAccessRecord, ...]:
        stmt = (
            select(ProjectMembershipModel, ProjectModel)
            .join(ProjectModel, ProjectModel.id == ProjectMembershipModel.project_id)
            .where(
                ProjectMembershipModel.user_id == user_id,
                ProjectMembershipModel.valid_from <= at,
                or_(ProjectMembershipModel.valid_to.is_(None), ProjectMembershipModel.valid_to > at),
                ProjectModel.lifecycle_status.notin_(
                    [ProjectLifecycleStatus.DELETION_PENDING.value, ProjectLifecycleStatus.DELETED.value]
                ),
            )
            .order_by(ProjectModel.code)
        )
        rows = (await self._session.execute(stmt)).all()
        return tuple(
            MembershipAccessRecord(
                company_id=project.company_id,
                client_id=project.client_id,
                project_id=project.id,
                project_code=project.code,
                role=ProjectRole(membership.role),
                valid_from=membership.valid_from,
                valid_to=membership.valid_to,
            )
            for membership, project in rows
        )

    async def list_published_document_access(
        self, *, project_id: UUID
    ) -> list[DocumentAccessRecord]:
        stmt = (
            select(
                DocumentVersionModel.document_id,
                DocumentVersionModel.id,
                DocumentVersionModel.version_no,
                DocumentModel.document_category,
            )
            .join(DocumentModel, DocumentModel.id == DocumentVersionModel.document_id)
            .where(
                DocumentModel.project_id == project_id,
                DocumentVersionModel.lifecycle_status == DocumentLifecycleStatus.PUBLISHED.value,
            )
            .order_by(DocumentVersionModel.document_id, DocumentVersionModel.version_no.desc())
        )
        rows = (await self._session.execute(stmt)).all()
        seen_documents: set[UUID] = set()
        result: list[DocumentAccessRecord] = []
        for document_id, version_id, _version_no, document_category in rows:
            if document_id in seen_documents:
                continue
            seen_documents.add(document_id)
            result.append(
                DocumentAccessRecord(
                    document_version_id=version_id,
                    document_category=document_category,
                )
            )
        return result

    async def list_active_knowledge_space_ids(self, *, project_id: UUID) -> tuple[str, ...]:
        stmt = (
            select(ProjectKnowledgeSpaceModel.external_space_id)
            .where(
                ProjectKnowledgeSpaceModel.project_id == project_id,
                ProjectKnowledgeSpaceModel.provider == "ragflow",
                ProjectKnowledgeSpaceModel.status == "active",
            )
            .order_by(ProjectKnowledgeSpaceModel.external_space_id)
        )
        return tuple((await self._session.scalars(stmt)).all())
