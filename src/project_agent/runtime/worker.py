from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from project_agent.agent.checkpoint import async_postgres_saver
from project_agent.application.ports.run_graph import RunGraphExecutor
from project_agent.config import Settings
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.jobs.postgres import PostgresJobQueue
from project_agent.infrastructure.llm.adapter import (
    OpenAICompatibleStructuredLLMAdapter,
    StructuredLLMRetryPolicy,
)
from project_agent.infrastructure.object_store.local import LocalFileObjectStoreAdapter
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.client import RagflowRetryPolicy
from project_agent.observability.cost import TokenCostPolicy
from project_agent.observability.logging import configure_structured_logging
from project_agent.observability.metrics import (
    MetricsHttpServerHandle,
    ObservabilityMetrics,
    start_metrics_http_server,
)
from project_agent.runtime.issue import ProductionIssueRunGraphExecutor
from project_agent.runtime.qa import build_production_qa_executor
from project_agent.runtime.run_graph import build_production_run_graph_executor
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
    metrics: ObservabilityMetrics
    metrics_server: MetricsHttpServerHandle | None


@asynccontextmanager
async def build_worker_runtime(
    settings: Settings,
    *,
    graph_executor_factory: GraphExecutorFactory | None = None,
    retention_repository: RetentionRepository | None = None,
) -> AsyncIterator[WorkerRuntime]:
    _validate_worker_configuration(settings, retention_repository)
    configure_structured_logging(log_level=settings.log_level)
    metrics = ObservabilityMetrics()
    cost_policy = TokenCostPolicy(
        settings.llm_input_cost_microunits_per_million_tokens,
        settings.llm_output_cost_microunits_per_million_tokens,
        settings.cost_currency,
    )
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    queue = PostgresJobQueue(
        session_factory,
        lease_seconds=settings.worker_lease_seconds,
        retry_base_seconds=settings.worker_retry_base_seconds,
        retry_max_seconds=settings.worker_retry_max_seconds,
        metrics=metrics,
    )

    metrics_server = (
        start_metrics_http_server(
            metrics=metrics,
            host=settings.worker_metrics_host,
            port=settings.worker_metrics_port,
        )
        if settings.worker_metrics_enabled
        else None
    )

    try:
        async with (
            async_postgres_saver(settings.database_url) as saver,
            _graph_executor_lifetime(
                settings,
                session_factory=session_factory,
                saver=saver,
                graph_executor_factory=graph_executor_factory,
            ) as graph_executor,
        ):
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
                metrics=metrics,
                cost_policy=cost_policy,
            )
            runtime = WorkerRuntime(
                settings=settings,
                engine=engine,
                session_factory=session_factory,
                queue=queue,
                handlers=handlers,
                worker=worker,
                metrics=metrics,
                metrics_server=metrics_server,
            )
            try:
                yield runtime
            finally:
                worker.stop()
                close = getattr(graph_executor, "aclose", None)
                if callable(close):
                    await close()
    finally:
        if metrics_server is not None:
            metrics_server.close()
        await engine.dispose()


@asynccontextmanager
async def _graph_executor_lifetime(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    saver: object,
    graph_executor_factory: GraphExecutorFactory | None,
) -> AsyncIterator[RunGraphExecutor]:
    if graph_executor_factory is not None:
        yield graph_executor_factory(saver)
        return
    async with _default_qa_executor_lifetime(
        settings,
        session_factory=session_factory,
        saver=saver,
    ) as graph_executor:
        yield graph_executor


@asynccontextmanager
async def _default_qa_executor_lifetime(
    settings: Settings,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    saver: object,
) -> AsyncIterator[RunGraphExecutor]:
    async with (
        httpx.AsyncClient(
            base_url=settings.ragflow_base_url,
            timeout=settings.ragflow_request_timeout_seconds,
        ) as ragflow_http,
        httpx.AsyncClient(
            base_url=settings.llm_base_url,
            timeout=settings.llm_request_timeout_seconds,
        ) as llm_http,
    ):
        knowledge = RagflowAdapter.from_http_client(
            ragflow_http,
            api_key=settings.ragflow_api_key.get_secret_value(),
            object_store=LocalFileObjectStoreAdapter(settings.local_storage_root),
            embedding_model=settings.ragflow_embedding_model,
            chunk_method=settings.ragflow_chunk_method,
            retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
        )
        llm = OpenAICompatibleStructuredLLMAdapter(
            llm_http,
            api_key=settings.llm_api_key.get_secret_value(),
            retry_policy=StructuredLLMRetryPolicy(max_attempts=settings.llm_max_attempts),
            request_timeout_seconds=settings.llm_request_timeout_seconds,
        )
        qa = build_production_qa_executor(
            settings=settings,
            session_factory=session_factory,
            saver=saver,
            knowledge=knowledge,
            llm=llm,
            llm_usage=llm,
        )
        issue = ProductionIssueRunGraphExecutor(
            settings,
            saver,
            knowledge=knowledge,
        )
        yield build_production_run_graph_executor(qa=qa, issue=issue)


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
