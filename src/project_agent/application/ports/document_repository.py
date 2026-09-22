from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from project_agent.domain.enums import DocumentLifecycleStatus


@dataclass(frozen=True, slots=True)
class DocumentVersionRecord:
    company_id: UUID
    project_id: UUID
    document_id: UUID
    version_id: UUID
    document_category: str
    title: str
    version_no: int
    version_label: str
    authority_level: str
    lifecycle_status: DocumentLifecycleStatus
    owner_user_id: UUID | None
    created_by: UUID
    source_uri: str
    content_hash: str
    effective_from: date | None = None
    effective_to: date | None = None
    supersedes_version_id: UUID | None = None
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CreateDocumentDraft:
    company_id: UUID
    project_id: UUID
    document_id: UUID | None
    document_category: str
    title: str
    version_label: str
    authority_level: str
    owner_user_id: UUID | None
    created_by: UUID
    source_uri: str
    content_hash: str
    effective_from: date | None = None
    effective_to: date | None = None
    supersedes_version_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DocumentAuditRecord:
    action: str
    project_id: UUID
    version_id: UUID
    user_id: UUID | None
    outcome: str = "success"
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DocumentWorkflowRepository(Protocol):
    async def create_draft(self, draft: CreateDocumentDraft) -> DocumentVersionRecord: ...

    async def get_version(self, version_id: UUID) -> DocumentVersionRecord: ...

    async def transition(
        self,
        version_id: UUID,
        *,
        expected: DocumentLifecycleStatus,
        target: DocumentLifecycleStatus,
    ) -> DocumentVersionRecord: ...

    async def complete_publication(
        self,
        version_id: UUID,
        *,
        supersedes_version_id: UUID | None,
    ) -> DocumentVersionRecord: ...

    async def add_audit(self, audit: DocumentAuditRecord) -> None: ...

    async def project_code(self, project_id: UUID) -> str: ...

    async def knowledge_space_id(self, project_id: UUID) -> str: ...
