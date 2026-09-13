from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from project_agent.application.ports.document_repository import (
    CreateDocumentDraft,
    DocumentAuditRecord,
    DocumentVersionRecord,
    DocumentWorkflowRepository,
)
from project_agent.application.ports.object_store import ObjectStorePort, PutObjectRequest
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.metadata import MetadataSuggestion


class DocumentActor(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    permissions: frozenset[str] = frozenset()


class UploadDocumentCommand(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    company_id: UUID
    project_id: UUID
    document_id: UUID | None = None
    document_category: DocumentCategory
    title: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    authority_level: AuthorityLevel
    filename: str = Field(min_length=1)
    data: bytes = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    owner_user_id: UUID | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    supersedes_version_id: UUID | None = None
    actor: DocumentActor
    suggestion: MetadataSuggestion | None = None


class UploadDocumentUseCase:
    def __init__(
        self,
        repository: DocumentWorkflowRepository,
        object_store: ObjectStorePort,
    ) -> None:
        self._repository = repository
        self._object_store = object_store

    async def execute(self, command: UploadDocumentCommand) -> DocumentVersionRecord:
        # Physical filenames are never derived from the uploaded filename. The original
        # filename is only preserved in the audit payload.
        logical_object_key = f"objects/{uuid4().hex}"
        stored = await self._object_store.put(
            PutObjectRequest(
                project_id=str(command.project_id),
                object_key=logical_object_key,
                data=command.data,
                mime_type=command.mime_type,
            )
        )
        record = await self._repository.create_draft(
            CreateDocumentDraft(
                company_id=command.company_id,
                project_id=command.project_id,
                document_id=command.document_id,
                document_category=command.document_category.value,
                title=command.title,
                version_label=command.version_label,
                authority_level=command.authority_level.value,
                owner_user_id=command.owner_user_id,
                created_by=command.actor.user_id,
                source_uri=stored.object_key,
                content_hash=stored.sha256,
                effective_from=command.effective_from,
                effective_to=command.effective_to,
                supersedes_version_id=command.supersedes_version_id,
            )
        )
        if record.lifecycle_status is not DocumentLifecycleStatus.DRAFT:
            raise RuntimeError("upload repository must create DRAFT only")

        suggestion_payload = (
            command.suggestion.model_dump(mode="json") if command.suggestion is not None else None
        )
        await self._repository.add_audit(
            DocumentAuditRecord(
                action="document_metadata_confirmed",
                project_id=command.project_id,
                version_id=record.version_id,
                user_id=command.actor.user_id,
                details={
                    "filename": command.filename,
                    "suggestion": suggestion_payload,
                    "suggestion_confidence": (
                        command.suggestion.confidence if command.suggestion is not None else None
                    ),
                    "final": {
                        "project_id": str(command.project_id),
                        "document_category": command.document_category.value,
                        "title": command.title,
                        "version_label": command.version_label,
                        "authority_level": command.authority_level.value,
                        "effective_from": (
                            command.effective_from.isoformat() if command.effective_from else None
                        ),
                        "effective_to": (
                            command.effective_to.isoformat() if command.effective_to else None
                        ),
                        "supersedes_version_id": (
                            str(command.supersedes_version_id)
                            if command.supersedes_version_id
                            else None
                        ),
                    },
                    "confirmed_by": str(command.actor.user_id),
                },
            )
        )
        return record
