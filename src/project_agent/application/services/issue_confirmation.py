from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from project_agent.application.ports.issue_workflow import IssueWorkflowRepository
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.issues import (
    ConfirmationAction,
    ConfirmationRequest,
    IssueDraftStatus,
    ToolConfirmationReceipt,
    ToolConfirmationStatus,
)


class ConfirmationPayloadMismatch(ValueError):
    pass


class ConfirmationExpired(PermissionError):
    pass


class IssueConfirmationService:
    TOOL_NAME = "project_tracker.create_issue"

    def __init__(
        self,
        repository: IssueWorkflowRepository,
        *,
        drafts: IssueDraftService,
        ttl: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._drafts = drafts
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(UTC))

    async def prepare(self, draft_id: UUID) -> ConfirmationRequest:
        draft = await self._repository.get_draft(draft_id)
        request = self._drafts.build_create_request(draft)
        return ConfirmationRequest(
            draft_id=draft.id,
            tool_name=self.TOOL_NAME,
            request_id=request.request_id,
            request_payload_hash=self._drafts.payload_hash(request),
            expires_at=draft.created_at + self._ttl,
            title=request.title,
            description=request.description,
            issue_type=request.issue_type,
            priority=request.priority,
            module=request.module,
            error_code=request.error_code,
            environment=request.environment,
            possible_duplicates=await self._repository.list_candidate_links(draft.id),
        )

    async def record_decision(
        self,
        *,
        draft_id: UUID,
        actor_id: UUID,
        action: ConfirmationAction,
        request_payload_hash: str,
    ) -> ToolConfirmationReceipt:
        prepared = await self.prepare(draft_id)
        now = self._clock()
        if now > prepared.expires_at:
            raise ConfirmationExpired("issue creation confirmation expired")
        if request_payload_hash != prepared.request_payload_hash:
            raise ConfirmationPayloadMismatch("confirmation payload hash does not match draft")
        status = (
            ToolConfirmationStatus.CONFIRMED
            if action is ConfirmationAction.CONFIRM
            else ToolConfirmationStatus.CANCELLED
        )
        draft = await self._repository.get_draft(draft_id)
        receipt = await self._repository.save_confirmation(
            ToolConfirmationReceipt(
                id=uuid4(),
                run_id=draft.run_id,
                tool_name=self.TOOL_NAME,
                request_payload_hash=prepared.request_payload_hash,
                status=status,
                confirmed_by=actor_id,
                confirmed_at=now,
                expires_at=prepared.expires_at,
            )
        )
        await self._repository.set_draft_status(
            draft_id,
            IssueDraftStatus.CONFIRMED
            if status is ToolConfirmationStatus.CONFIRMED
            else IssueDraftStatus.CANCELLED,
        )
        return receipt
