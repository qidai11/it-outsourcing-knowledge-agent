from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from project_agent.application.ports.job_queue import EnqueueJobRequest, JobEnqueuePort
from project_agent.application.ports.run_repository import RunRepository
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationService,
)
from project_agent.domain.runs import (
    AgentEventType,
    RunBusinessMode,
    RunJobType,
    RunRecord,
)


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
            raise RunAccessDenied("run company does not match current authorization")
        return run
