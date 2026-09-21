from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from pydantic import SecretStr

from project_agent.application.ports.knowledge import KnowledgeRetrievalPort
from project_agent.application.services.authorization import (
    AuthorizationService,
    AuthorizedProjectContext,
)
from project_agent.config import Settings
from project_agent.domain.access import ProjectAccessScope
from project_agent.domain.runs import RunBusinessMode
from project_agent.runtime.issue import (
    ProductionIssueRunGraphExecutor,
    build_issue_graph_executor_factory,
)


def _settings() -> Settings:
    return Settings(
        app_env="development",
        database_url="postgresql+asyncpg://agent:agent@localhost:5432/agent",
        local_storage_root=Path("./data"),
        ragflow_base_url="http://localhost:9380",
        ragflow_api_key=SecretStr("ragflow-test-key"),
        ragflow_expected_version="v0-test",
        llm_base_url="https://llm.example.test/v1",
        llm_api_key=SecretStr("llm-test-key"),
        llm_model_alias="test-model",
        llm_request_capacity=10,
        llm_token_capacity=100_000,
        retention_sweep_enabled=False,
    )


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def _executor(monkeypatch: pytest.MonkeyPatch) -> tuple[ProductionIssueRunGraphExecutor, object]:
    import project_agent.runtime.issue as module

    engine = _FakeEngine()
    session_factory = cast(Any, object())
    monkeypatch.setattr(module, "create_engine", lambda _url: engine)
    monkeypatch.setattr(module, "create_session_factory", lambda _engine: session_factory)
    knowledge = cast(KnowledgeRetrievalPort, object())
    return ProductionIssueRunGraphExecutor(_settings(), object(), knowledge=knowledge), engine


def test_issue_runtime_module_exists() -> None:
    assert importlib.util.find_spec("project_agent.runtime.issue") is not None


def test_issue_runtime_dispatches_lookup_and_create_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import project_agent.runtime.issue as module

    executor, _ = _executor(monkeypatch)
    lookup_graph = object()
    create_graph = object()
    seen: dict[str, object] = {}

    def build_lookup(deps: object, *, checkpointer: object | None = None) -> object:
        seen["lookup_deps"] = deps
        seen["lookup_checkpointer"] = checkpointer
        return lookup_graph

    def build_create(deps: object, *, checkpointer: object | None = None) -> object:
        seen["create_deps"] = deps
        seen["create_checkpointer"] = checkpointer
        return create_graph

    monkeypatch.setattr(module, "build_issue_lookup_run_graph", build_lookup)
    monkeypatch.setattr(module, "build_issue_create_run_graph", build_create)
    session = cast(Any, object())

    assert executor._build_graph(RunBusinessMode.ISSUE_LOOKUP, session) is lookup_graph
    assert executor._build_graph(RunBusinessMode.ISSUE_CREATE, session) is create_graph
    assert seen["lookup_checkpointer"] is executor._checkpointer
    assert seen["create_checkpointer"] is executor._checkpointer
    assert seen["create_deps"].knowledge is executor._knowledge

    fake_run_graph = ModuleType("project_agent.workers.run_graph")

    class FakeRunGraphUnavailable(RuntimeError):
        pass

    fake_run_graph.RunGraphUnavailable = FakeRunGraphUnavailable  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "project_agent.workers.run_graph", fake_run_graph)
    with pytest.raises(FakeRunGraphUnavailable, match="qa"):
        executor._build_graph(RunBusinessMode.QA, session)


def test_issue_graph_executor_factory_preserves_shared_checkpointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import project_agent.runtime.issue as module

    engine = _FakeEngine()
    monkeypatch.setattr(module, "create_engine", lambda _url: engine)
    monkeypatch.setattr(module, "create_session_factory", lambda _engine: cast(Any, object()))
    knowledge = cast(KnowledgeRetrievalPort, object())
    checkpointer = object()

    factory = build_issue_graph_executor_factory(_settings(), knowledge=knowledge)
    executor = factory(checkpointer)

    assert isinstance(executor, ProductionIssueRunGraphExecutor)
    assert executor._checkpointer is checkpointer
    assert executor._knowledge is knowledge


@pytest.mark.asyncio
async def test_issue_runtime_closes_owned_engine_without_owning_injected_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, engine = _executor(monkeypatch)

    await executor.aclose()

    assert cast(_FakeEngine, engine).disposed is True
    assert executor._http is None


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def __call__(self) -> _FakeSession:
        return self.session


def _run(mode: RunBusinessMode, *, user_id=None, project_id=None):  # type: ignore[no-untyped-def]
    from uuid import uuid4

    from project_agent.domain.runs import RunRecord, RunStatus

    return RunRecord(
        id=uuid4(),
        thread_id=uuid4(),
        company_id=uuid4(),
        project_id=project_id or uuid4(),
        user_id=user_id or uuid4(),
        business_mode=mode,
        status=RunStatus.RUNNING,
        started_at=None,
        finished_at=None,
    )


@pytest.mark.asyncio
async def test_issue_runtime_commits_graph_business_transaction_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind

    executor, _ = _executor(monkeypatch)
    session = _FakeSession()
    executor._session_factory = cast(Any, _FakeSessionFactory(session))
    monkeypatch.setattr(executor, "_build_graph", lambda _mode, _session: object())
    fake_run_graph = ModuleType("project_agent.workers.run_graph")

    class FakeDelegate:
        def __init__(self, _graphs: object) -> None:
            pass

        async def execute(self, _run_record: object) -> RunGraphOutcome:
            return RunGraphOutcome(kind=RunGraphOutcomeKind.SUCCEEDED, result_ref="candidate:1")

        async def resume(
            self, _run_record: object, _resume_payload: dict[str, object]
        ) -> RunGraphOutcome:
            raise AssertionError("resume not expected")

    fake_run_graph.LangGraphRunExecutor = FakeDelegate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "project_agent.workers.run_graph", fake_run_graph)

    outcome = await executor.execute(_run(RunBusinessMode.ISSUE_LOOKUP))

    assert outcome.result_ref == "candidate:1"
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_issue_runtime_rolls_back_graph_business_transaction_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, _ = _executor(monkeypatch)
    session = _FakeSession()
    executor._session_factory = cast(Any, _FakeSessionFactory(session))
    monkeypatch.setattr(executor, "_build_graph", lambda _mode, _session: object())
    fake_run_graph = ModuleType("project_agent.workers.run_graph")

    class FailingDelegate:
        def __init__(self, _graphs: object) -> None:
            pass

        async def execute(self, _run_record: object) -> object:
            raise RuntimeError("graph failed")

        async def resume(self, _run_record: object, _resume_payload: dict[str, object]) -> object:
            raise RuntimeError("graph failed")

    fake_run_graph.LangGraphRunExecutor = FailingDelegate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "project_agent.workers.run_graph", fake_run_graph)

    with pytest.raises(RuntimeError, match="graph failed"):
        await executor.execute(_run(RunBusinessMode.ISSUE_LOOKUP))

    assert session.commits == 0
    assert session.rollbacks == 1


class _BindingKnowledge:
    def __init__(self) -> None:
        self.bindings: list[tuple[str, str]] = []

    def bind_authorized_space(self, *, project_id: str, dataset_id: str) -> None:
        self.bindings.append((project_id, dataset_id))


@pytest.mark.asyncio
async def test_issue_create_runtime_binds_db_authorized_knowledge_spaces_before_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    import project_agent.runtime.issue as module
    from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind

    engine = _FakeEngine()
    session = _FakeSession()
    factory = _FakeSessionFactory(session)
    monkeypatch.setattr(module, "create_engine", lambda _url: engine)
    monkeypatch.setattr(module, "create_session_factory", lambda _engine: factory)
    knowledge = _BindingKnowledge()
    executor = ProductionIssueRunGraphExecutor(
        _settings(),
        object(),
        knowledge=cast(KnowledgeRetrievalPort, knowledge),
    )

    project_id = uuid4()
    user_id = uuid4()
    scope = ProjectAccessScope(
        company_id=uuid4(),
        user_id=user_id,
        allowed_client_ids=(uuid4(),),
        allowed_project_ids=(project_id,),
        allowed_document_version_ids=(uuid4(),),
        allowed_document_categories=("requirement_baseline",),
        role_ids=("developer",),
        max_security_level=0,
        policy_version="project-membership-v1",
    )
    context = AuthorizedProjectContext(
        scope=scope,
        project_code="WS7-ISSUE-A",
        knowledge_space_ids=("dataset-a", "dataset-b"),
    )

    async def authorize_project(self, *, user_id, project_id):  # type: ignore[no-untyped-def]
        del self, user_id, project_id
        return context

    monkeypatch.setattr(AuthorizationService, "authorize_project", authorize_project)
    monkeypatch.setattr(executor, "_build_graph", lambda _mode, _session: object())

    fake_run_graph = ModuleType("project_agent.workers.run_graph")

    class FakeDelegate:
        def __init__(self, _graphs: object) -> None:
            pass

        async def execute(self, _run_record: object) -> RunGraphOutcome:
            return RunGraphOutcome(kind=RunGraphOutcomeKind.WAITING_CONFIRMATION)

        async def resume(
            self, _run_record: object, _resume_payload: dict[str, object]
        ) -> RunGraphOutcome:
            raise AssertionError("resume not expected")

    fake_run_graph.LangGraphRunExecutor = FakeDelegate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "project_agent.workers.run_graph", fake_run_graph)

    outcome = await executor.execute(
        _run(RunBusinessMode.ISSUE_CREATE, user_id=user_id, project_id=project_id)
    )

    assert outcome.kind is RunGraphOutcomeKind.WAITING_CONFIRMATION
    assert knowledge.bindings == [
        ("WS7-ISSUE-A", "dataset-a"),
        ("WS7-ISSUE-A", "dataset-b"),
    ]
    assert session.commits == 1
    assert session.rollbacks == 0
