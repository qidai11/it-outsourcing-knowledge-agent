from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import SecretStr
from tests.fakes.run_graph import FakeRunGraphExecutor

from project_agent.config import Settings
from project_agent.runtime.worker import WorkerConfigurationError, build_worker_runtime
from project_agent.workers.handlers import (
    DELETE_DOCUMENT,
    EXECUTE_AGENT_RUN,
    INGEST_DOCUMENT,
    RECONCILE_ISSUE_CREATE,
    RESUME_AGENT_RUN,
    RETENTION_SWEEP,
    UnknownJobType,
)
from project_agent.workers.retention import RetentionCandidate


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "development",
        "database_url": "postgresql+asyncpg://agent:agent@localhost:5432/agent",
        "local_storage_root": Path("./data"),
        "ragflow_base_url": "http://localhost:9380",
        "ragflow_api_key": SecretStr("ragflow-test-key"),
        "ragflow_expected_version": "v0-test",
        "llm_base_url": "https://llm.example.test/v1",
        "llm_api_key": SecretStr("llm-test-key"),
        "llm_model_alias": "test-model",
        "llm_request_capacity": 10,
        "llm_token_capacity": 100_000,
        "retention_sweep_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeRetentionRepository:
    async def list_candidates(self, policy_id: str) -> list[RetentionCandidate]:
        del policy_id
        return []

    async def delete_candidate(self, candidate: RetentionCandidate) -> None:
        del candidate


@pytest.fixture
def runtime_dependencies(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    import project_agent.runtime.worker as module

    engine = FakeEngine()
    session_factory = cast(Any, object())
    saver = object()
    lifetime = {"entered": False, "exited": False}

    monkeypatch.setattr(module, "create_engine", lambda _url: engine)
    monkeypatch.setattr(module, "create_session_factory", lambda _engine: session_factory)

    @asynccontextmanager
    async def fake_saver(_url: str):  # type: ignore[no-untyped-def]
        lifetime["entered"] = True
        try:
            yield saver
        finally:
            lifetime["exited"] = True

    monkeypatch.setattr(module, "async_postgres_saver", fake_saver)
    return {
        "engine": engine,
        "session_factory": session_factory,
        "saver": saver,
        "lifetime": lifetime,
    }


@pytest.mark.asyncio
async def test_runtime_registers_run_and_reconciliation_handlers(
    runtime_dependencies: dict[str, object],
) -> None:
    seen_savers: list[object] = []

    def graph_factory(saver: object) -> FakeRunGraphExecutor:
        seen_savers.append(saver)
        return FakeRunGraphExecutor()

    async with build_worker_runtime(settings(), graph_executor_factory=graph_factory) as runtime:
        assert runtime.handlers.resolve(EXECUTE_AGENT_RUN)
        assert runtime.handlers.resolve(RESUME_AGENT_RUN)
        assert runtime.handlers.resolve(RECONCILE_ISSUE_CREATE)
        assert seen_savers == [runtime_dependencies["saver"]]


@pytest.mark.asyncio
async def test_runtime_keeps_document_jobs_explicitly_disabled(
    runtime_dependencies: dict[str, object],
) -> None:
    async with build_worker_runtime(
        settings(),
        graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
    ) as runtime:
        with pytest.raises(UnknownJobType):
            runtime.handlers.resolve(INGEST_DOCUMENT)
        with pytest.raises(UnknownJobType):
            runtime.handlers.resolve(DELETE_DOCUMENT)
        with pytest.raises(UnknownJobType):
            runtime.handlers.resolve("UNKNOWN_JOB")


@pytest.mark.asyncio
async def test_enabling_unsupported_document_job_fails_at_startup() -> None:
    with pytest.raises(WorkerConfigurationError, match="INGEST_DOCUMENT"):
        async with build_worker_runtime(
            settings(worker_ingest_document_enabled=True),
            graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
        ):
            pass


@pytest.mark.asyncio
async def test_retention_enabled_without_repository_fails_at_startup() -> None:
    with pytest.raises(WorkerConfigurationError, match="RETENTION_SWEEP"):
        async with build_worker_runtime(
            settings(retention_sweep_enabled=True),
            graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
        ):
            pass


@pytest.mark.asyncio
async def test_retention_registration_follows_explicit_setting(
    runtime_dependencies: dict[str, object],
) -> None:
    repository = FakeRetentionRepository()
    async with build_worker_runtime(
        settings(retention_sweep_enabled=True),
        graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
        retention_repository=repository,
    ) as runtime:
        assert runtime.handlers.resolve(RETENTION_SWEEP)

    async with build_worker_runtime(
        settings(retention_sweep_enabled=False),
        graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
    ) as runtime:
        with pytest.raises(UnknownJobType):
            runtime.handlers.resolve(RETENTION_SWEEP)


@pytest.mark.asyncio
async def test_runtime_projects_queue_and_worker_settings(
    runtime_dependencies: dict[str, object],
) -> None:
    configured = settings(
        worker_concurrency=7,
        worker_claim_limit=5,
        worker_lease_seconds=41.0,
        worker_heartbeat_seconds=9.0,
        worker_poll_seconds=0.25,
        worker_retry_base_seconds=1.5,
        worker_retry_max_seconds=77.0,
    )

    async with build_worker_runtime(
        configured,
        graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
    ) as runtime:
        assert runtime.queue._lease.total_seconds() == 41.0
        assert runtime.queue._retry_base == 1.5
        assert runtime.queue._retry_max == 77.0
        assert runtime.worker._settings.concurrency == 7
        assert runtime.worker._settings.claim_limit == 5
        assert runtime.worker._settings.heartbeat_seconds == 9.0
        assert runtime.worker._settings.poll_seconds == 0.25


@pytest.mark.asyncio
async def test_runtime_closes_worker_checkpointer_and_engine(
    runtime_dependencies: dict[str, object],
) -> None:
    async with build_worker_runtime(
        settings(),
        graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
    ) as runtime:
        assert runtime_dependencies["lifetime"] == {"entered": True, "exited": False}
        assert runtime.worker._stop.is_set() is False

    assert runtime.worker._stop.is_set() is True
    assert runtime_dependencies["lifetime"] == {"entered": True, "exited": True}
    assert cast(FakeEngine, runtime_dependencies["engine"]).disposed is True


@pytest.mark.asyncio
async def test_runtime_closes_optional_graph_executor_resource(
    runtime_dependencies: dict[str, object],
) -> None:
    class ClosableExecutor(FakeRunGraphExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    executor = ClosableExecutor()
    async with build_worker_runtime(
        settings(),
        graph_executor_factory=lambda _saver: executor,
    ):
        assert executor.closed is False

    assert executor.closed is True
