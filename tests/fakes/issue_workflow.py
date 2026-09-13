from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from project_agent.domain.issues import (
    IdempotencyRecord,
    IdempotencyStatus,
    IssueCandidateLink,
    IssueDraft,
    IssueDraftCreate,
    IssueDraftStatus,
    ToolConfirmationReceipt,
    ToolConfirmationStatus,
)


class FakeIssueWorkflowRepository:
    def __init__(self, *, clock=None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self.drafts: dict[UUID, IssueDraft] = {}
        self.candidates: dict[UUID, list[IssueCandidateLink]] = {}
        self.confirmations: dict[UUID, ToolConfirmationReceipt] = {}

    async def create_draft(self, command: IssueDraftCreate) -> IssueDraft:
        now = self._clock()
        draft = IssueDraft(id=uuid4(), created_at=now, updated_at=now, **command.model_dump())
        self.drafts[draft.id] = draft
        return draft

    async def get_draft(self, draft_id: UUID) -> IssueDraft:
        return self.drafts[draft_id]

    async def set_draft_status(self, draft_id: UUID, status: IssueDraftStatus) -> IssueDraft:
        draft = self.drafts[draft_id].model_copy(update={"status": status, "updated_at": self._clock()})
        self.drafts[draft_id] = draft
        return draft

    async def save_candidate_links(self, draft_id: UUID, links: tuple[IssueCandidateLink, ...]) -> None:
        self.candidates[draft_id] = list(links)

    async def list_candidate_links(self, draft_id: UUID) -> tuple[IssueCandidateLink, ...]:
        return tuple(self.candidates.get(draft_id, ()))

    async def save_confirmation(self, receipt: ToolConfirmationReceipt) -> ToolConfirmationReceipt:
        for existing in self.confirmations.values():
            if (
                existing.run_id == receipt.run_id
                and existing.tool_name == receipt.tool_name
                and existing.request_payload_hash == receipt.request_payload_hash
                and existing.status == receipt.status
                and existing.confirmed_by == receipt.confirmed_by
            ):
                return existing
        self.confirmations[receipt.id] = receipt
        return receipt

    async def get_confirmation(self, confirmation_id: UUID) -> ToolConfirmationReceipt:
        return self.confirmations[confirmation_id]


class FakeIdempotencyStore:
    def __init__(self, *, clock=None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self.records: dict[tuple[str, str], IdempotencyRecord] = {}

    async def reserve(self, *, namespace: str, request_id: str, project_id: UUID) -> tuple[IdempotencyRecord, bool]:
        key = (namespace, request_id)
        existing = self.records.get(key)
        if existing is not None:
            return existing, False
        now = self._clock()
        record = IdempotencyRecord(
            id=uuid4(), namespace=namespace, request_id=request_id, project_id=project_id,
            status=IdempotencyStatus.IN_PROGRESS, resource_type=None, resource_id=None,
            response=None, created_at=now, updated_at=now,
        )
        self.records[key] = record
        return record, True

    async def get(self, *, namespace: str, request_id: str) -> IdempotencyRecord | None:
        return self.records.get((namespace, request_id))

    async def complete(self, *, namespace: str, request_id: str, resource_type: str, resource_id: str, response: dict[str, object]) -> IdempotencyRecord:
        key = (namespace, request_id)
        current = self.records[key]
        done = current.model_copy(update={
            "status": IdempotencyStatus.COMPLETED,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "response": response,
            "updated_at": self._clock(),
        })
        self.records[key] = done
        return done
