from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from project_agent.domain.enums import DocumentLifecycleStatus


class DocumentMetadataInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    document_category: str
    title: str
    version_label: str
    authority_level: str
    lifecycle_status: DocumentLifecycleStatus
    effective_from: date | None = None
    effective_to: date | None = None
    supersedes_version_id: UUID | None = None


class MetadataSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    suggested_project_id: UUID | None = None
    suggested_document_category: str | None = None
    suggested_version_label: str | None = None
    suggested_authority_level: str | None = None
    suggested_effective_from: date | None = None
    suggested_supersedes_version_id: UUID | None = None
    confidence: float | None = None
    evidence: tuple[str, ...] = ()
