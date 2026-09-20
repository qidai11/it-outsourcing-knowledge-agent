from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from project_agent.application.ports.job_queue import EnqueueJobRequest, JobEnqueuePort
from project_agent.application.ports.run_repository import RunRepository
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationService,
)
from project_agent.domain.issues import ConfirmationAction
from project_agent.domain.runs import (
    AgentEventType,
    RunBusinessMode,
    RunJobType,
    RunRecord,
    RunStatus,
)
from project_agent.observability.logging import get_logger
from project_agent.observability.metrics import current_metrics


@dataclass(frozen=True, slots=True)
class ResumeRunCommand:
    action: ConfirmationAction
    request_payload_hash: str


@dataclass(frozen=True, slots=True)
class CreateRunCommand:
    project_id: UUID
    business_mode: RunBusinessMode
    query_text: str
    thread_id: UUID | None = None


class RunNotFound(LookupError):
    """Raised when a requested run does not exist."""


class ThreadNotFound(LookupError):
    """Raised when a supplied thread does not exist."""


class RunAccessDenied(PermissionError):
    """Raised when durable ownership does not match current authorization."""


class RunStateConflict(RuntimeError):
    """Raised when a Run cannot accept the requested state transition."""


class ResumeInputMismatch(RunStateConflict):
    """Raised when resume input does not match the durable interrupt payload."""


class RunApplicationService:
    def __init__(
        self,
        *,
        authorization: AuthorizationService,
        repository: RunRepository,
        jobs: JobEnqueuePort,
    ) -> None:
        self._authorization = authorization
        self._repository = repository
        self._jobs = jobs

    async def create_run(
        self,
        *,
        identity: AuthenticatedIdentity,
        command: CreateRunCommand,
    ) -> RunRecord:
        query_text = command.query_text.strip()
        if not query_text:
            raise ValueError("query text must not be blank")

        authorized = await self._authorization.authorize_identity(
            identity=identity,
            project_id=command.project_id,
        )
        company_id = authorized.scope.company_id

        if command.thread_id is None:
            thread = await self._repository.create_thread(
                company_id=company_id,
                project_id=command.project_id,
                user_id=identity.user_id,
            )
        else:
            existing_thread = await self._repository.get_thread(command.thread_id)
            if existing_thread is None:
                raise ThreadNotFound(f"thread {command.thread_id} not found")
            thread = existing_thread
            if (
                thread.project_id != command.project_id
                or thread.company_id != company_id
                or thread.user_id != identity.user_id
            ):
                _observe_run_denial("scope_mismatch")
                raise RunAccessDenied("thread does not belong to the authorized actor scope")

        run = await self._repository.create_run(
            thread_id=thread.id,
            company_id=company_id,
            project_id=command.project_id,
            user_id=identity.user_id,
            business_mode=command.business_mode,
        )
        await self._repository.append_event(
            run_id=run.id,
            event_type=AgentEventType.RUN_QUEUED,
            payload={"query_text": query_text},
        )
        await self._jobs.enqueue(
            EnqueueJobRequest(
                job_type=RunJobType.EXECUTE.value,
                aggregate_id=str(run.id),
            )
        )
        return run

    async def resume_run(
        self,
        *,
        identity: AuthenticatedIdentity,
        run_id: UUID,
        command: ResumeRunCommand,
    ) -> RunRecord:
        run = await self._repository.get_run(run_id, for_update=True)
        if run is None:
            raise RunNotFound(f"run {run_id} not found")

        authorized = await self._authorization.authorize_identity(
            identity=identity,
            project_id=run.project_id,
        )
        if authorized.scope.company_id != run.company_id:
            _observe_run_denial("scope_mismatch")
            raise RunAccessDenied("run company does not match current authorization")
        if identity.user_id != run.user_id:
            _observe_run_denial("actor_mismatch")
            raise RunAccessDenied("only the original run actor may resume this run")
        if run.business_mode is not RunBusinessMode.ISSUE_CREATE:
            raise RunStateConflict("run business mode does not accept confirmation resume")
        if run.status is not RunStatus.WAITING_CONFIRMATION:
            raise RunStateConflict("run is not waiting for confirmation")

        waiting = await self._repository.latest_event_of_type(
            run_id=run.id,
            event_type=AgentEventType.WAITING_CONFIRMATION,
        )
        if waiting is None:
            raise RunStateConflict("run has no durable waiting confirmation event")
        expected_hash = waiting.payload.get("request_payload_hash")
        if not isinstance(expected_hash, str):
            raise RunStateConflict("waiting confirmation event has no payload hash")
        if command.request_payload_hash != expected_hash:
            raise ResumeInputMismatch("resume payload hash does not match waiting confirmation")

        await self._repository.append_event(
            run_id=run.id,
            event_type=AgentEventType.RUN_RESUME_QUEUED,
            payload={
                "action": command.action.value,
                "request_payload_hash": command.request_payload_hash,
                "actor_id": str(identity.user_id),
            },
        )
        updated = await self._repository.set_status(
            run_id=run.id,
            status=RunStatus.QUEUED,
        )
        await self._jobs.enqueue(
            EnqueueJobRequest(
                job_type=RunJobType.RESUME.value,
                aggregate_id=str(run.id),
            )
        )
        return updated

    async def get_run(
        self,
        *,
        identity: AuthenticatedIdentity,
        run_id: UUID,
    ) -> RunRecord:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise RunNotFound(f"run {run_id} not found")

        authorized = await self._authorization.authorize_identity(
            identity=identity,
            project_id=run.project_id,
        )
        if authorized.scope.company_id != run.company_id:
            _observe_run_denial("scope_mismatch")
            raise RunAccessDenied("run company does not match current authorization")
        return run


def _observe_run_denial(reason: str) -> None:
    metrics = current_metrics()
    if metrics is not None:
        if reason == "scope_mismatch":
            metrics.observe_authorization_denial(reason="scope_mismatch")
        elif reason == "actor_mismatch":
            metrics.observe_authorization_denial(reason="actor_mismatch")
    get_logger().info("authorization_denied", reason=reason)
