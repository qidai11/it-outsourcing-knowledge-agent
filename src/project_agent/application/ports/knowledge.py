from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class IngestionState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class EnsureKnowledgeSpaceRequest:
    project_id: str
    space_key: str


@dataclass(frozen=True, slots=True)
class KnowledgeSpace:
    knowledge_space_id: str
    project_id: str
    space_key: str


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionRequest:
    project_id: str
    knowledge_space_id: str
    document_version_id: str
    object_key: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionReceipt:
    ingestion_job_id: str
    project_id: str
    document_version_id: str


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionStatus:
    ingestion_job_id: str
    state: IngestionState
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalRequest:
    project_id: str
    query: str
    limit: int = 10
    document_version_ids: tuple[str, ...] = ()
    knowledge_space_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    project_id: str
    document_version_id: str
    content: str
    score: float
    knowledge_space_id: str | None = None
    provider_ref: str | None = None
    page_no: int | None = None
    section: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeleteKnowledgeDocumentRequest:
    project_id: str
    document_version_id: str
    knowledge_space_id: str


@runtime_checkable
class KnowledgeIngestionPort(Protocol):
    async def ingest(self, request: KnowledgeIngestionRequest) -> KnowledgeIngestionReceipt: ...

    async def get_ingestion_status(self, ingestion_job_id: str) -> KnowledgeIngestionStatus: ...


@runtime_checkable
class KnowledgeRetrievalPort(Protocol):
    async def retrieve(self, request: KnowledgeRetrievalRequest) -> list[KnowledgeChunk]: ...


@runtime_checkable
class KnowledgeAdminPort(Protocol):
    async def ensure_space(self, request: EnsureKnowledgeSpaceRequest) -> KnowledgeSpace: ...

    async def delete_document(self, request: DeleteKnowledgeDocumentRequest) -> None: ...
