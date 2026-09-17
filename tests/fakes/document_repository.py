from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from project_agent.application.ports.document_repository import (
    CreateDocumentDraft,
    DocumentAuditRecord,
    DocumentVersionRecord,
)
from project_agent.domain.documents import transition_document_status
from project_agent.domain.enums import DocumentLifecycleStatus


class InMemoryDocumentWorkflowRepository:
    def __init__(self) -> None:
        self._versions: dict[UUID, DocumentVersionRecord] = {}
        self._knowledge_spaces: dict[UUID, str] = {}
        self._project_codes: dict[UUID, str] = {}
        self.audits: list[DocumentAuditRecord] = []

    async def create_draft(self, draft: CreateDocumentDraft) -> DocumentVersionRecord:
        document_id = draft.document_id or uuid4()
        same_document = [v for v in self._versions.values() if v.document_id == document_id]
        version_no = max((v.version_no for v in same_document), default=0) + 1
        if same_document:
            original = same_document[0]
            if original.project_id != draft.project_id:
                raise ValueError("document cannot move across projects")
            if original.document_category != draft.document_category:
                raise ValueError("new version cannot change document category")
        record = DocumentVersionRecord(
            company_id=draft.company_id,
            project_id=draft.project_id,
            document_id=document_id,
            version_id=uuid4(),
            document_category=draft.document_category,
            title=draft.title,
            version_no=version_no,
            version_label=draft.version_label,
            authority_level=draft.authority_level,
            lifecycle_status=DocumentLifecycleStatus.DRAFT,
            owner_user_id=draft.owner_user_id,
            created_by=draft.created_by,
            source_uri=draft.source_uri,
            content_hash=draft.content_hash,
            effective_from=draft.effective_from,
            effective_to=draft.effective_to,
            supersedes_version_id=draft.supersedes_version_id,
        )
        self._versions[record.version_id] = record
        return record

    async def get_version(self, version_id: UUID) -> DocumentVersionRecord:
        return self._versions[version_id]

    def get_now(self, version_id: UUID) -> DocumentVersionRecord:
        return self._versions[version_id]

    async def transition(
        self,
        version_id: UUID,
        *,
        expected: DocumentLifecycleStatus,
        target: DocumentLifecycleStatus,
    ) -> DocumentVersionRecord:
        current = self._versions[version_id]
        if current.lifecycle_status is not expected:
            raise ValueError(f"expected {expected}, got {current.lifecycle_status}")
        transition_document_status(current.lifecycle_status, target)
        updated = replace(current, lifecycle_status=target)
        self._versions[version_id] = updated
        return updated

    async def complete_publication(
        self,
        version_id: UUID,
        *,
        supersedes_version_id: UUID | None,
    ) -> DocumentVersionRecord:
        current = self._versions[version_id]
        if current.lifecycle_status is not DocumentLifecycleStatus.APPROVED:
            raise ValueError("only APPROVED version can complete publication")
        if supersedes_version_id is not None:
            old = self._versions[supersedes_version_id]
            if old.lifecycle_status is not DocumentLifecycleStatus.PUBLISHED:
                raise ValueError("superseded version must still be PUBLISHED")
        published = replace(
            current,
            lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
            published_at=datetime.now(UTC),
        )
        if supersedes_version_id is not None:
            old = self._versions[supersedes_version_id]
            self._versions[supersedes_version_id] = replace(
                old, lifecycle_status=DocumentLifecycleStatus.SUPERSEDED
            )
        self._versions[version_id] = published
        return published

    async def add_audit(self, audit: DocumentAuditRecord) -> None:
        self.audits.append(audit)

    async def project_code(self, project_id: UUID) -> str:
        return self._project_codes[project_id]

    async def knowledge_space_id(self, project_id: UUID) -> str:
        return self._knowledge_spaces[project_id]

    def bind_project_code(self, project_id: UUID, project_code: str) -> None:
        self._project_codes[project_id] = project_code

    def bind_knowledge_space(self, project_id: UUID, knowledge_space_id: str) -> None:
        self._knowledge_spaces[project_id] = knowledge_space_id

    def seed_version(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        document_category: str,
        title: str,
        version_label: str,
        authority_level: str,
        lifecycle_status: DocumentLifecycleStatus,
        owner_user_id: UUID | None,
    ) -> DocumentVersionRecord:
        record = DocumentVersionRecord(
            company_id=company_id,
            project_id=project_id,
            document_id=uuid4(),
            version_id=uuid4(),
            document_category=document_category,
            title=title,
            version_no=1,
            version_label=version_label,
            authority_level=authority_level,
            lifecycle_status=lifecycle_status,
            owner_user_id=owner_user_id,
            created_by=uuid4(),
            source_uri=f"objects/{uuid4().hex}",
            content_hash=uuid4().hex,
        )
        self._versions[record.version_id] = record
        return record
