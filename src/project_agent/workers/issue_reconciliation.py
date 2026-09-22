from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_agent.application.ports.job_queue import JobQueuePort, QueuedJob
from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.issue_creation import IssueCreationService
from project_agent.infrastructure.db.repositories.authorization import (
    SqlAlchemyProjectAuthorizationRepository,
)
from project_agent.infrastructure.db.repositories.issue_workflow import (
    PostgresIdempotencyStore,
    SqlAlchemyIssueWorkflowRepository,
)
from project_agent.infrastructure.project_tracker.sandbox import SandboxProjectTrackerAdapter


class ReconcileIssueCreateHandler:
    def __init__(self, creation: IssueCreationService) -> None:
        self._creation = creation

    async def __call__(self, job: QueuedJob) -> object:
        return await self._creation.reconcile(UUID(job.aggregate_id))


class ProductionReconcileIssueCreateHandler:
    """Build Task 13 reconciliation dependencies inside a job-scoped transaction."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        job_queue: JobQueuePort,
    ) -> None:
        self._session_factory = session_factory
        self._job_queue = job_queue
        self._idempotency = PostgresIdempotencyStore(session_factory)

    async def __call__(self, job: QueuedJob) -> object:
        async with self._session_factory() as session:
            workflow_repo = SqlAlchemyIssueWorkflowRepository(session)
            creation = IssueCreationService(
                workflow_repo=workflow_repo,
                idempotency=self._idempotency,
                tracker=SandboxProjectTrackerAdapter(session),
                authorization=AuthorizationService(
                    SqlAlchemyProjectAuthorizationRepository(session)
                ),
                job_queue=self._job_queue,
            )
            result = await ReconcileIssueCreateHandler(creation)(job)
            await session.commit()
            return result
