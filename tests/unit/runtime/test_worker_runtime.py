from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from tests.fakes.run_graph import FakeRunGraphExecutor

from project_agent.config import Settings
from project_agent.domain.runs import RunBusinessMode, RunRecord, RunStatus
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
        "worker_metrics_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def make_run(mode: RunBusinessMode) -> RunRecord:
    return RunRecord(
        id=uuid4(),
        thread_id=uuid4(),
        company_id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        business_mode=mode,
        status=RunStatus.RUNNING,
        started_at=datetime.now(UTC),
        finished_at=None,
    )


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

async def test_injected_graph_factory_bypasses_default_provider_clients(
    runtime_dependencies: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import project_agent.runtime.worker as module

    called = False

    @asynccontextmanager
    async def forbidden_default(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        nonlocal called
        called = True
        raise AssertionError("default provider composition must not run for injected factory")
        yield  # pragma: no cover

    monkeypatch.setattr(module, "_default_qa_executor_lifetime", forbidden_default, raising=False)

    async with build_worker_runtime(
        settings(),
        graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
    ) as runtime:
        assert runtime.handlers.resolve(EXECUTE_AGENT_RUN)

    assert called is False


@pytest.mark.asyncio
async def test_default_worker_runtime_builds_unified_qa_and_issue_executor(
    runtime_dependencies: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import project_agent.runtime.worker as module

    knowledge = object()
    qa = FakeRunGraphExecutor()

    class FakeIssueExecutor(FakeRunGraphExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    issue = FakeIssueExecutor()
    seen_qa: list[dict[str, object]] = []
    seen_issue: list[dict[str, object]] = []
    seen_object_store_roots: list[Path] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            del exc_type, exc, tb

    class FakeRagflowAdapter:
        @classmethod
        def from_http_client(cls, http, **kwargs):  # type: ignore[no-untyped-def]
            del http, kwargs
            return knowledge

    class FakeLLMAdapter:
        def __init__(self, http, **kwargs):  # type: ignore[no-untyped-def]
            self.http = http
            self.kwargs = kwargs

    class FakeObjectStore:
        def __init__(self, root: Path) -> None:
            seen_object_store_roots.append(root)

    def fake_qa_builder(**kwargs: object) -> FakeRunGraphExecutor:
        seen_qa.append(kwargs)
        return qa

    def fake_issue_executor(
        configured: Settings,
        saver: object,
        *,
        knowledge: object,
    ) -> FakeIssueExecutor:
        seen_issue.append(
            {"settings": configured, "saver": saver, "knowledge": knowledge}
        )
        return issue

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(module, "RagflowAdapter", FakeRagflowAdapter)
    monkeypatch.setattr(module, "OpenAICompatibleStructuredLLMAdapter", FakeLLMAdapter)
    monkeypatch.setattr(module, "LocalFileObjectStoreAdapter", FakeObjectStore, raising=False)
    monkeypatch.setattr(module, "build_production_qa_executor", fake_qa_builder)
    monkeypatch.setattr(
        module,
        "ProductionIssueRunGraphExecutor",
        fake_issue_executor,
        raising=False,
    )

    configured = settings()
    async with build_worker_runtime(configured) as runtime:
        execute = cast(Any, runtime.handlers.resolve(EXECUTE_AGENT_RUN))
        resume = cast(Any, runtime.handlers.resolve(RESUME_AGENT_RUN))
        graph = execute._graph

        assert resume._graph is graph
        assert seen_qa[0]["saver"] is runtime_dependencies["saver"]
        assert seen_issue == [
            {
                "settings": configured,
                "saver": runtime_dependencies["saver"],
                "knowledge": knowledge,
            }
        ]
        assert seen_qa[0]["knowledge"] is knowledge
        assert seen_object_store_roots == [configured.local_storage_root]

        qa_run = make_run(RunBusinessMode.QA)
        lookup_run = make_run(RunBusinessMode.ISSUE_LOOKUP)
        create_run = make_run(RunBusinessMode.ISSUE_CREATE)
        await graph.execute(qa_run)
        await graph.execute(lookup_run)
        await graph.execute(create_run)
        await graph.resume(create_run, {"action": "confirm"})

        assert qa.execute_calls == [qa_run]
        assert issue.execute_calls == [lookup_run, create_run]
        assert issue.resume_calls == [(create_run, {"action": "confirm"})]
        assert issue.closed is False

    assert issue.closed is True


@pytest.mark.asyncio
async def test_default_worker_runtime_owns_provider_clients_and_preserves_ws3_handlers(
    runtime_dependencies: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import project_agent.runtime.worker as module
    from project_agent.workers.run_execution import ExecuteAgentRunHandler, ResumeAgentRunHandler

    created: list[dict[str, object]] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.closed = False
            created.append({"client": self, **kwargs})

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            self.closed = True

    class FakeRagflowAdapter:
        @classmethod
        def from_http_client(cls, http, **kwargs):  # type: ignore[no-untyped-def]
            return ("ragflow", http, kwargs)

    class FakeLLMAdapter:
        def __init__(self, http, **kwargs):  # type: ignore[no-untyped-def]
            self.http = http
            self.kwargs = kwargs

    seen_builder: list[dict[str, object]] = []
    seen_issue: list[dict[str, object]] = []

    class FakeIssueExecutor(FakeRunGraphExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    issue = FakeIssueExecutor()

    def fake_builder(**kwargs: object) -> FakeRunGraphExecutor:
        seen_builder.append(kwargs)
        return FakeRunGraphExecutor()

    def fake_issue_executor(
        configured: Settings,
        saver: object,
        *,
        knowledge: object,
    ) -> FakeIssueExecutor:
        seen_issue.append(
            {"settings": configured, "saver": saver, "knowledge": knowledge}
        )
        return issue

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(module, "RagflowAdapter", FakeRagflowAdapter)
    monkeypatch.setattr(module, "OpenAICompatibleStructuredLLMAdapter", FakeLLMAdapter)
    monkeypatch.setattr(module, "build_production_qa_executor", fake_builder)
    monkeypatch.setattr(
        module,
        "ProductionIssueRunGraphExecutor",
        fake_issue_executor,
        raising=False,
    )

    configured = settings(
        ragflow_request_timeout_seconds=12.5,
        ragflow_max_attempts=4,
        llm_request_timeout_seconds=7.5,
        llm_max_attempts=2,
    )
    async with build_worker_runtime(configured) as runtime:
        execute = runtime.handlers.resolve(EXECUTE_AGENT_RUN)
        resume = runtime.handlers.resolve(RESUME_AGENT_RUN)
        assert isinstance(execute, ExecuteAgentRunHandler)
        assert isinstance(resume, ResumeAgentRunHandler)
        assert len(created) == 2
        assert created[0]["base_url"] == configured.ragflow_base_url
        assert created[0]["timeout"] == 12.5
        assert created[1]["base_url"] == configured.llm_base_url
        assert created[1]["timeout"] == 7.5
        assert len(seen_builder) == 1
        assert seen_builder[0]["session_factory"] is runtime_dependencies["session_factory"]
        assert seen_builder[0]["saver"] is runtime_dependencies["saver"]
        assert seen_builder[0]["llm"] is seen_builder[0]["llm_usage"]
        assert seen_issue == [
            {
                "settings": configured,
                "saver": runtime_dependencies["saver"],
                "knowledge": seen_builder[0]["knowledge"],
            }
        ]
        assert issue.closed is False
        assert all(not entry["client"].closed for entry in created)  # type: ignore[union-attr]

    assert issue.closed is True
    assert all(entry["client"].closed for entry in created)  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_worker_runtime_owns_metrics_server_lifecycle(
    runtime_dependencies: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import project_agent.runtime.worker as module

    seen: list[tuple[object, str, int]] = []

    class FakeHandle:
        def __init__(self) -> None:
            self.closed = False
        def close(self) -> None:
            self.closed = True

    handle = FakeHandle()

    def fake_start(*, metrics, host: str, port: int):  # type: ignore[no-untyped-def]
        seen.append((metrics, host, port))
        return handle

    monkeypatch.setattr(module, "start_metrics_http_server", fake_start)
    configured = settings(
        worker_metrics_enabled=True,
        worker_metrics_host="127.0.0.1",
        worker_metrics_port=9101,
    )
    async with build_worker_runtime(
        configured,
        graph_executor_factory=lambda _saver: FakeRunGraphExecutor(),
    ) as runtime:
        assert seen == [(runtime.metrics, "127.0.0.1", 9101)]
        assert handle.closed is False
    assert handle.closed is True
