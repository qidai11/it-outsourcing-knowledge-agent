from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from project_agent.agent.checkpoint import async_postgres_saver
from project_agent.application.ports.run_graph import RunGraphExecutor
from project_agent.config import Settings
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.jobs.postgres import PostgresJobQueue
from project_agent.workers.handlers import (
    EXECUTE_AGENT_RUN,
    RECONCILE_ISSUE_CREATE,
    RESUME_AGENT_RUN,
    RETENTION_SWEEP,
    HandlerRegistry,
)
from project_agent.workers.issue_reconciliation import ProductionReconcileIssueCreateHandler
from project_agent.workers.main import BackgroundWorker, WorkerSettings
from project_agent.workers.retention import RetentionRepository, RetentionSweepHandler
from project_agent.workers.run_execution import ExecuteAgentRunHandler, ResumeAgentRunHandler

type GraphExecutorFactory = Callable[[object], RunGraphExecutor]


class WorkerConfigurationError(RuntimeError):
    """Raised when a configured Worker job has no safe WS3 implementation."""


@dataclass(slots=True)
class WorkerRuntime:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    queue: PostgresJobQueue
    handlers: HandlerRegistry
    worker: BackgroundWorker


@asynccontextmanager
async def build_worker_runtime(
    settings: Settings,
    *,
    graph_executor_factory: GraphExecutorFactory,
    retention_repository: RetentionRepository | None = None,
) -> AsyncIterator[WorkerRuntime]:
    _validate_worker_configuration(settings, retention_repository)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    queue = PostgresJobQueue(
        session_factory,
        lease_seconds=settings.worker_lease_seconds,
        retry_base_seconds=settings.worker_retry_base_seconds,
        retry_max_seconds=settings.worker_retry_max_seconds,
    )

    try:
        async with async_postgres_saver(settings.database_url) as saver:
            graph_executor = graph_executor_factory(saver)
            handlers = _build_handler_registry(
                settings,
                session_factory=session_factory,
                queue=queue,
                graph_executor=graph_executor,
                retention_repository=retention_repository,
            )
            worker = BackgroundWorker(
                queue,
                handlers,
                worker_id=f"{socket.gethostname()}:{os.getpid()}",
                settings=WorkerSettings(
                    concurrency=settings.worker_concurrency,
                    claim_limit=settings.worker_claim_limit,
                    heartbeat_seconds=settings.worker_heartbeat_seconds,
                    poll_seconds=settings.worker_poll_seconds,
                ),
            )
            runtime = WorkerRuntime(
                settings=settings,
                engine=engine,
                session_factory=session_factory,
                queue=queue,
                handlers=handlers,
                worker=worker,
            )
            try:
                yield runtime
            finally:
                worker.stop()
    finally:
        await engine.dispose()


def _validate_worker_configuration(
    settings: Settings,
    retention_repository: RetentionRepository | None,
) -> None:
    if settings.worker_ingest_document_enabled:
        raise WorkerConfigurationError(
            "INGEST_DOCUMENT is intentionally disabled in WS3"
        )
    if settings.worker_delete_document_enabled:
        raise WorkerConfigurationError(
            "DELETE_DOCUMENT is intentionally disabled in WS3"
        )
    if settings.retention_sweep_enabled and retention_repository is None:
        raise WorkerConfigurationError(
            "RETENTION_SWEEP requires an injected RetentionRepository when enabled"
        )


def _build_handler_registry(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    queue: PostgresJobQueue,
    graph_executor: RunGraphExecutor,
    retention_repository: RetentionRepository | None,
) -> HandlerRegistry:
    handlers = HandlerRegistry()
    handlers.register(
        EXECUTE_AGENT_RUN,
        ExecuteAgentRunHandler(session_factory, graph_executor),
    )
    handlers.register(
        RESUME_AGENT_RUN,
        ResumeAgentRunHandler(session_factory, graph_executor),
    )
    handlers.register(
        RECONCILE_ISSUE_CREATE,
        ProductionReconcileIssueCreateHandler(session_factory, queue),
    )
    if settings.retention_sweep_enabled:
        if retention_repository is None:
            raise WorkerConfigurationError(
                "RETENTION_SWEEP requires an injected RetentionRepository when enabled"
            )
        handlers.register(
            RETENTION_SWEEP,
            RetentionSweepHandler(
                retention_repository,
                dry_run=settings.retention_sweep_dry_run,
            ),
        )
    return handlers
