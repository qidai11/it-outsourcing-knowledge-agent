from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus


@dataclass(frozen=True, slots=True)
class GovernedEvidence:
    label: str
    project_id: UUID
    project_code: str
    document_version_id: UUID
    document_category: DocumentCategory
    document_title: str
    version_no: int
    version_label: str
    authority_level: AuthorityLevel
    lifecycle_status: DocumentLifecycleStatus
    is_current: bool
    effective_from: date | None
    effective_to: date | None
    content: str
    score: float
    knowledge_space_id: str | None
    provider_ref: str | None
    page_no: int | None
    section: str | None
    provider_metadata: dict[str, str]
    conflict_key: str | None
    claim_value: str | None
    unresolved_conflict: bool

    @property
    def content_hash(self) -> str:
        payload = "\n".join(
            (
                str(self.project_id),
                str(self.document_version_id),
                self.authority_level.value,
                self.version_label,
                self.content,
            )
        )
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernedEvidencePack:
    evidence: tuple[GovernedEvidence, ...]
    unresolved_conflicts: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class FrozenEvidence:
    snapshot_id: UUID
    label: str
    project_id: UUID
    project_code: str
    document_version_id: UUID
    document_category: DocumentCategory
    document_title: str
    version_no: int
    version_label: str
    authority_level: AuthorityLevel
    lifecycle_status: DocumentLifecycleStatus
    is_current: bool
    effective_from: date | None
    effective_to: date | None
    content: str
    content_hash: str
    score: float
    knowledge_space_id: str | None
    provider_ref: str | None
    page_no: int | None
    section: str | None
    conflict_key: str | None
    claim_value: str | None
    unresolved_conflict: bool


@dataclass(frozen=True, slots=True)
class FrozenEvidenceBundle:
    evidence: tuple[FrozenEvidence, ...]
    unresolved_conflicts: dict[str, tuple[str, ...]]


class GroundedAnswerClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class ConflictDisclosure(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class GroundedAnswerDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    claims: tuple[GroundedAnswerClaim, ...] = ()
    conflict_disclosure: ConflictDisclosure | None = None


@dataclass(frozen=True, slots=True)
class CitationReference:
    citation_no: int
    evidence_snapshot_id: UUID
