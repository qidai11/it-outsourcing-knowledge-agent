from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IssueDraftStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    CREATED = "CREATED"


class ConfirmationAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"


class ToolConfirmationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class IssueDraftCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    project_id: UUID
    created_by: UUID
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1)
    issue_type: str
    proposed_priority: str
    module: str | None = None
    environment: str | None = None
    reproduction_steps: tuple[str, ...] = ()
    expected_behavior: str | None = None
    actual_behavior: str | None = None
    evidence_ids: tuple[str, ...] = ()
    status: IssueDraftStatus = IssueDraftStatus.DRAFT


class IssueDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    project_id: UUID
    created_by: UUID
    title: str
    description: str
    issue_type: str
    proposed_priority: str
    module: str | None = None
    environment: str | None = None
    reproduction_steps: tuple[str, ...] = ()
    expected_behavior: str | None = None
    actual_behavior: str | None = None
    evidence_ids: tuple[str, ...] = ()
    status: IssueDraftStatus
    created_at: datetime
    updated_at: datetime


class IssueCandidateLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    issue_key: str
    rank: int = Field(ge=1)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reasons: tuple[str, ...] = ()


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft_id: UUID
    tool_name: str
    request_id: str
    request_payload_hash: str
    expires_at: datetime
    title: str
    description: str
    issue_type: str
    priority: str
    module: str | None = None
    error_code: str | None = None
    environment: str | None = None
    evidence_ids: tuple[str, ...] = ()
    possible_duplicates: tuple[IssueCandidateLink, ...] = ()


class ToolConfirmationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    run_id: UUID
    tool_name: str
    request_payload_hash: str
    status: ToolConfirmationStatus
    confirmed_by: UUID
    confirmed_at: datetime
    expires_at: datetime


class IdempotencyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    namespace: str
    request_id: str
    project_id: UUID
    status: IdempotencyStatus
    resource_type: str | None = None
    resource_id: str | None = None
    response: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime
