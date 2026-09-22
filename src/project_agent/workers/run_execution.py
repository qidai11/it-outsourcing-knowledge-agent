from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_agent.application.ports.job_queue import QueuedJob
from project_agent.application.ports.run_graph import RunGraphExecutor, RunGraphOutcome
from project_agent.application.services.run_execution import (
    RunExecutionPreparation,
    RunExecutionService,
)
from project_agent.infrastructure.db.repositories.runs import SqlAlchemyRunRepository

type RunExecutionServiceFactory = Callable[[AsyncSession], RunExecutionService]


class _RunJobHandler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        graph: RunGraphExecutor,
        *,
        service_factory: RunExecutionServiceFactory | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._graph = graph
        self._service_factory = service_factory or self._default_service_factory

    @staticmethod
    def _default_service_factory(session: AsyncSession) -> RunExecutionService:
        return RunExecutionService(SqlAlchemyRunRepository(session))

    async def _persist_outcome(self, run_id: UUID, outcome: RunGraphOutcome) -> None:
        async with self._session_factory() as session:
            service = self._service_factory(session)
            await service.persist_outcome(run_id, outcome)
            await session.commit()

    async def _persist_final_failure(self, run_id: UUID, error_code: str) -> None:
        async with self._session_factory() as session:
            service = self._service_factory(session)
            await service.mark_final_failure(run_id, error_code)
            await session.commit()

    async def _handle_failure(self, job: QueuedJob, run_id: UUID, exc: Exception) -> None:
        if job.attempts >= job.max_attempts:
            await self._persist_final_failure(run_id, type(exc).__name__)


class ExecuteAgentRunHandler(_RunJobHandler):
    async def __call__(self, job: QueuedJob) -> None:
        run_id = UUID(job.aggregate_id)
        async with self._session_factory() as session:
            service = self._service_factory(session)
            preparation = await service.prepare_execute(run_id)
            await session.commit()

        if not preparation.invoke:
            return

        try:
            outcome = await self._graph.execute(preparation.run)
        except Exception as exc:
            await self._handle_failure(job, run_id, exc)
            raise

        await self._persist_outcome(run_id, outcome)


class ResumeAgentRunHandler(_RunJobHandler):
    async def __call__(self, job: QueuedJob) -> None:
        run_id = UUID(job.aggregate_id)
        async with self._session_factory() as session:
            service = self._service_factory(session)
            preparation = await service.prepare_resume(run_id)
            await session.commit()

        if not preparation.invoke:
            return

        resume_payload = _resume_payload(preparation)
        try:
            outcome = await self._graph.resume(
                preparation.run,
                resume_payload,
            )
        except Exception as exc:
            await self._handle_failure(job, run_id, exc)
            raise

        await self._persist_outcome(run_id, outcome)


def _resume_payload(preparation: RunExecutionPreparation) -> dict[str, object]:
    if preparation.resume_payload is None:
        raise RuntimeError("resume preparation did not provide durable payload")
    return dict(preparation.resume_payload)
