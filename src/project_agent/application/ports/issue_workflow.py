from __future__ import annotations

from typing import Protocol
from uuid import UUID

from project_agent.domain.issues import (
    IdempotencyRecord,
    IssueCandidateLink,
    IssueDraft,
    IssueDraftCreate,
    IssueDraftStatus,
    ToolConfirmationReceipt,
)


class IssueWorkflowRepository(Protocol):
    async def create_draft(self, command: IssueDraftCreate) -> IssueDraft: ...

    async def get_draft(self, draft_id: UUID) -> IssueDraft: ...

    async def set_draft_status(self, draft_id: UUID, status: IssueDraftStatus) -> IssueDraft: ...

    async def save_candidate_links(
        self, draft_id: UUID, links: tuple[IssueCandidateLink, ...]
    ) -> None: ...

    async def list_candidate_links(self, draft_id: UUID) -> tuple[IssueCandidateLink, ...]: ...

    async def save_confirmation(
        self, receipt: ToolConfirmationReceipt
    ) -> ToolConfirmationReceipt: ...

    async def get_confirmation(self, confirmation_id: UUID) -> ToolConfirmationReceipt: ...


class IdempotencyStorePort(Protocol):
    async def reserve(
        self, *, namespace: str, request_id: str, project_id: UUID
    ) -> tuple[IdempotencyRecord, bool]: ...

    async def get(
        self, *, namespace: str, request_id: str
    ) -> IdempotencyRecord | None: ...

    async def complete(
        self,
        *,
        namespace: str,
        request_id: str,
        resource_type: str,
        resource_id: str,
        response: dict[str, object],
    ) -> IdempotencyRecord: ...
