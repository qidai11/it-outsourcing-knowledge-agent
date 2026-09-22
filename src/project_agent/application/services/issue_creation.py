from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from project_agent.application.ports.issue_workflow import (
    IdempotencyStorePort,
    IssueWorkflowRepository,
)
from project_agent.application.ports.job_queue import EnqueueJobRequest, JobQueuePort
from project_agent.application.ports.project_tracker import CreatedIssue, ProjectTrackerPort
from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.enums import ProjectRole
from project_agent.domain.issues import IdempotencyStatus, IssueDraftStatus, ToolConfirmationStatus
from project_agent.observability.logging import get_logger
from project_agent.observability.metrics import current_metrics
from project_agent.workers.handlers import RECONCILE_ISSUE_CREATE


class IssueCreationDenied(PermissionError):
    pass


class IssueCreationStatus(StrEnum):
    CREATED = "CREATED"
    ALREADY_CREATED = "ALREADY_CREATED"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"
    RECONCILED = "RECONCILED"


class IssueCreationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: IssueCreationStatus
    draft_id: UUID
    request_id: str
    issue_key: str | None = None
    issue_status: str | None = None


class IssueWritePolicy:
    ALLOWED_ROLES = frozenset(
        {
            ProjectRole.PROJECT_MANAGER.value,
            ProjectRole.DEVELOPER.value,
            ProjectRole.QA.value,
            ProjectRole.IMPLEMENTATION.value,
            ProjectRole.SUPPORT.value,
        }
    )

    def assert_can_create(self, role_ids: tuple[str, ...]) -> None:
        if not self.ALLOWED_ROLES.intersection(role_ids):
            metrics = current_metrics()
            if metrics is not None:
                metrics.observe_authorization_denial(reason="role_denied")
            get_logger().info("authorization_denied", reason="role_denied")
            raise IssueCreationDenied("current project role cannot create issues")


class IssueCreationService:
    IDEMPOTENCY_NAMESPACE = "sandbox_issue_create"

    def __init__(
        self,
        *,
        workflow_repo: IssueWorkflowRepository,
        idempotency: IdempotencyStorePort,
        tracker: ProjectTrackerPort,
        authorization: AuthorizationService,
        job_queue: JobQueuePort,
        drafts: IssueDraftService | None = None,
        write_policy: IssueWritePolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._workflow_repo = workflow_repo
        self._idempotency = idempotency
        self._tracker = tracker
        self._authorization = authorization
        self._job_queue = job_queue
        self._drafts = drafts or IssueDraftService(workflow_repo)
        self._write_policy = write_policy or IssueWritePolicy()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        draft_id: UUID,
        confirmation_id: UUID,
        actor_id: UUID,
    ) -> IssueCreationOutcome:
        try:
            return await self._execute(
                draft_id=draft_id, confirmation_id=confirmation_id, actor_id=actor_id
            )
        except IssueCreationDenied:
            _observe_issue_create("denied")
            raise

    async def _execute(
        self,
        *,
        draft_id: UUID,
        confirmation_id: UUID,
        actor_id: UUID,
    ) -> IssueCreationOutcome:
        draft = await self._workflow_repo.get_draft(draft_id)
        try:
            confirmation = await self._workflow_repo.get_confirmation(confirmation_id)
        except (KeyError, LookupError):
            raise IssueCreationDenied("valid confirmation is required") from None
        if confirmation.status is not ToolConfirmationStatus.CONFIRMED:
            raise IssueCreationDenied("confirmed tool action is required")
        if confirmation.confirmed_by != actor_id:
            raise IssueCreationDenied("confirmation belongs to another user")
        request = self._drafts.build_create_request(draft)
        if self._drafts.payload_hash(request) != confirmation.request_payload_hash:
            raise IssueCreationDenied("confirmation does not match current draft payload")
        if draft.status not in {IssueDraftStatus.CONFIRMED, IssueDraftStatus.CREATED}:
            raise IssueCreationDenied("draft is not confirmed")

        context = await self._authorization.authorize_project(
            user_id=actor_id, project_id=draft.project_id
        )
        self._write_policy.assert_can_create(context.scope.role_ids)

        # Completed replays are read-only: return the durable result even if the
        # original confirmation TTL has since expired. A new external side effect
        # still requires an unexpired confirmation below.
        existing_record = await self._idempotency.get(
            namespace=self.IDEMPOTENCY_NAMESPACE,
            request_id=request.request_id,
        )
        if existing_record is not None and existing_record.status is IdempotencyStatus.COMPLETED:
            return self._outcome_from_record(
                existing_record.response, draft.id, request.request_id
            )
        if self._clock() > confirmation.expires_at and existing_record is None:
            raise IssueCreationDenied("confirmation expired")

        record, created_reservation = await self._idempotency.reserve(
            namespace=self.IDEMPOTENCY_NAMESPACE,
            request_id=request.request_id,
            project_id=draft.project_id,
        )
        if record.status is IdempotencyStatus.COMPLETED:
            return self._outcome_from_record(record.response, draft.id, request.request_id)

        # A pre-existing IN_PROGRESS reservation means another attempt already crossed
        # the durable idempotency barrier. Reconcile first; never issue a blind write.
        if not created_reservation:
            existing = await self._tracker.get_issue_by_request_id(
                request.project_id, request.request_id
            )
            if existing is not None:
                return await self._complete(
                    draft_id=draft.id,
                    request_id=request.request_id,
                    created=existing,
                    status=IssueCreationStatus.ALREADY_CREATED,
                )
            await self._enqueue_reconciliation(draft.id)
            outcome = IssueCreationOutcome(
                status=IssueCreationStatus.PENDING_RECONCILIATION,
                draft_id=draft.id,
                request_id=request.request_id,
            )
            _observe_issue_create("pending_reconciliation")
            return outcome

        existing = await self._tracker.get_issue_by_request_id(
            request.project_id, request.request_id
        )
        if existing is not None:
            return await self._complete(
                draft_id=draft.id,
                request_id=request.request_id,
                created=existing,
                status=IssueCreationStatus.ALREADY_CREATED,
            )

        try:
            created = await self._tracker.create_issue(request)
        except (TimeoutError, OSError):
            await self._enqueue_reconciliation(draft.id)
            outcome = IssueCreationOutcome(
                status=IssueCreationStatus.PENDING_RECONCILIATION,
                draft_id=draft.id,
                request_id=request.request_id,
            )
            _observe_issue_create("pending_reconciliation")
            return outcome
        return await self._complete(
            draft_id=draft.id,
            request_id=request.request_id,
            created=created,
            status=IssueCreationStatus.CREATED,
        )

    async def reconcile(self, draft_id: UUID) -> IssueCreationOutcome:
        draft = await self._workflow_repo.get_draft(draft_id)
        request = self._drafts.build_create_request(draft)
        record = await self._idempotency.get(
            namespace=self.IDEMPOTENCY_NAMESPACE,
            request_id=request.request_id,
        )
        if record is None:
            _observe_issue_create("denied")
            raise IssueCreationDenied(
                "reconciliation requires a prior confirmed idempotency barrier"
            )
        if record.status is IdempotencyStatus.COMPLETED:
            return self._outcome_from_record(
                record.response, draft.id, request.request_id, IssueCreationStatus.RECONCILED
            )
        existing = await self._tracker.get_issue_by_request_id(
            request.project_id, request.request_id
        )
        if existing is None:
            # Only a prior confirmed IN_PROGRESS barrier reaches this branch.
            # Provider-side request-id uniqueness makes replay with the same request safe.
            existing = await self._tracker.create_issue(request)
        return await self._complete(
            draft_id=draft.id,
            request_id=request.request_id,
            created=existing,
            status=IssueCreationStatus.RECONCILED,
        )

    async def _complete(
        self,
        *,
        draft_id: UUID,
        request_id: str,
        created: CreatedIssue,
        status: IssueCreationStatus,
    ) -> IssueCreationOutcome:
        response: dict[str, object] = {
            "project_id": created.project_id,
            "request_id": created.request_id,
            "issue_key": created.issue_key,
            "status": created.status,
        }
        await self._idempotency.complete(
            namespace=self.IDEMPOTENCY_NAMESPACE,
            request_id=request_id,
            resource_type="sandbox_issue",
            resource_id=created.issue_key,
            response=response,
        )
        await self._workflow_repo.set_draft_status(draft_id, IssueDraftStatus.CREATED)
        _observe_issue_create(status.value.lower())
        return IssueCreationOutcome(
            status=status,
            draft_id=draft_id,
            request_id=request_id,
            issue_key=created.issue_key,
            issue_status=created.status,
        )

    def _outcome_from_record(
        self,
        response: dict[str, object] | None,
        draft_id: UUID,
        request_id: str,
        status: IssueCreationStatus = IssueCreationStatus.ALREADY_CREATED,
    ) -> IssueCreationOutcome:
        if not response:
            raise RuntimeError("completed idempotency record has no response")
        _observe_issue_create(status.value.lower())
        return IssueCreationOutcome(
            status=status,
            draft_id=draft_id,
            request_id=request_id,
            issue_key=str(response["issue_key"]),
            issue_status=str(response["status"]),
        )

    async def _enqueue_reconciliation(self, draft_id: UUID) -> None:
        await self._job_queue.enqueue(
            EnqueueJobRequest(
                job_type=RECONCILE_ISSUE_CREATE,
                aggregate_id=str(draft_id),
                max_attempts=5,
            )
        )


def _observe_issue_create(outcome: str) -> None:
    metrics = current_metrics()
    if metrics is not None:
        if outcome == "created":
            metrics.observe_issue_create(outcome="created")
        elif outcome == "already_created":
            metrics.observe_issue_create(outcome="already_created")
        elif outcome == "pending_reconciliation":
            metrics.observe_issue_create(outcome="pending_reconciliation")
        elif outcome == "reconciled":
            metrics.observe_issue_create(outcome="reconciled")
        elif outcome == "denied":
            metrics.observe_issue_create(outcome="denied")
    event = (
        "issue_reconciliation_outcome"
        if outcome == "reconciled"
        else "issue_create_outcome"
    )
    get_logger().info(event, outcome=outcome)
