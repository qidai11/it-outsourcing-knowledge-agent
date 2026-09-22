from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from tests.fakes.llm import FakeStructuredLLM

from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind
from project_agent.application.services.authorization import (
    AuthorizationService,
    AuthorizedProjectContext,
)
from project_agent.config import Settings
from project_agent.domain.access import ProjectAccessScope
from project_agent.domain.runs import RunBusinessMode, RunRecord, RunStatus
from project_agent.infrastructure.db.repositories.authorization import (
    SqlAlchemyProjectAuthorizationRepository,
)
from project_agent.infrastructure.db.repositories.evidence_governance import (
    SqlAlchemyEvidenceGovernanceRepository,
)
from project_agent.infrastructure.db.repositories.identifiers import (
    SqlAlchemyIdentifierRegistryRepository,
)
from project_agent.infrastructure.db.repositories.qa_graph import SqlAlchemyQAGraphStore
from project_agent.infrastructure.db.repositories.system_config import (
    SqlAlchemyPromptConfigRepository,
)
from project_agent.runtime.qa import (
    ProductionQARunExecutor,
    build_production_qa_executor,
)


def settings() -> Settings:
    return Settings(
        app_env="development",
        database_url="postgresql+asyncpg://agent:agent@localhost:5432/agent",
        local_storage_root=Path("./data"),
        ragflow_base_url="http://ragflow.local",
        ragflow_api_key=SecretStr("ragflow-key"),
        ragflow_expected_version="v0-test",
        llm_base_url="https://llm.example.test/v1",
        llm_api_key=SecretStr("llm-key"),
        llm_model_alias="qa-model",
        llm_request_capacity=10,
        llm_token_capacity=100_000,
    )


def run_record(*, user_id=None, project_id=None) -> RunRecord:  # type: ignore[no-untyped-def]
    return RunRecord(
        id=uuid4(),
        thread_id=uuid4(),
        company_id=uuid4(),
        project_id=project_id or uuid4(),
        user_id=user_id or uuid4(),
        business_mode=RunBusinessMode.QA,
        status=RunStatus.RUNNING,
        started_at=datetime.now(UTC),
        finished_at=None,
    )


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class RecordingSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def __call__(self):  # type: ignore[no-untyped-def]
        session = FakeSession()
        self.sessions.append(session)

        @asynccontextmanager
        async def scope():  # type: ignore[no-untyped-def]
            yield session

        return scope()


class BindingKnowledge:
    def __init__(self) -> None:
        self.bindings: list[tuple[str, str]] = []

    def bind_authorized_space(self, *, project_id: str, dataset_id: str) -> None:
        self.bindings.append((project_id, dataset_id))


@pytest.mark.asyncio
async def test_dependency_builder_uses_existing_concrete_qa_services() -> None:
    session_factory = RecordingSessionFactory()
    knowledge = BindingKnowledge()
    llm = FakeStructuredLLM()
    executor = build_production_qa_executor(
        settings=settings(),
        session_factory=session_factory,  # type: ignore[arg-type]
        saver=object(),
        knowledge=knowledge,  # type: ignore[arg-type]
        llm=llm,
        llm_usage=llm,
    )
    assert isinstance(executor, ProductionQARunExecutor)

    session = FakeSession()
    deps = executor._build_dependencies(session)  # type: ignore[arg-type]

    assert isinstance(deps.authorization, AuthorizationService)
    assert isinstance(deps.authorization._repository, SqlAlchemyProjectAuthorizationRepository)
    assert isinstance(deps.prompt_config._repository, SqlAlchemyPromptConfigRepository)
    assert isinstance(deps.evidence_governance._repository, SqlAlchemyEvidenceGovernanceRepository)
    assert isinstance(
        deps.exact_resolver._registry._repository,
        SqlAlchemyIdentifierRegistryRepository,
    )
    assert isinstance(deps.store, SqlAlchemyQAGraphStore)
    assert deps.knowledge is knowledge
    assert deps.llm is llm
    assert deps.llm_usage is llm
    assert deps.model_alias == "qa-model"


@pytest.mark.asyncio
async def test_concurrent_execute_uses_distinct_sessions_and_only_db_authorized_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import project_agent.runtime.qa as module

    factory = RecordingSessionFactory()
    knowledge = BindingKnowledge()
    llm = FakeStructuredLLM()
    project_id = uuid4()
    user_id = uuid4()
    scope = ProjectAccessScope(
        company_id=uuid4(),
        user_id=user_id,
        allowed_client_ids=(uuid4(),),
        allowed_project_ids=(project_id,),
        allowed_document_version_ids=(uuid4(),),
        allowed_document_categories=("approved_design",),
        role_ids=("member",),
        max_security_level=0,
        policy_version="project-membership-v1",
    )
    context = AuthorizedProjectContext(
        scope=scope,
        project_code="PRJ-RETAIL-ALPHA",
        knowledge_space_ids=("dataset-a", "dataset-b"),
    )

    async def authorize_project(self, *, user_id, project_id):  # type: ignore[no-untyped-def]
        del self, user_id, project_id
        return context

    monkeypatch.setattr(AuthorizationService, "authorize_project", authorize_project)
    monkeypatch.setattr(module, "build_project_qa_graph", lambda deps, checkpointer=None: object())

    class Delegate:
        async def execute(self, run):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0)
            return RunGraphOutcome(RunGraphOutcomeKind.SUCCEEDED, result_ref=str(run.id))

    monkeypatch.setattr(module, "_build_langgraph_executor", lambda graph: Delegate())

    executor = build_production_qa_executor(
        settings=settings(),
        session_factory=factory,  # type: ignore[arg-type]
        saver=object(),
        knowledge=knowledge,  # type: ignore[arg-type]
        llm=llm,
        llm_usage=llm,
    )
    run1 = run_record(user_id=user_id, project_id=project_id)
    run2 = run_record(user_id=user_id, project_id=project_id)

    outcomes = await asyncio.gather(executor.execute(run1), executor.execute(run2))

    assert len(factory.sessions) == 2
    assert factory.sessions[0] is not factory.sessions[1]
    assert all(session.commits == 1 for session in factory.sessions)
    assert all(session.rollbacks == 0 for session in factory.sessions)
    assert outcomes == [
        RunGraphOutcome(RunGraphOutcomeKind.SUCCEEDED, result_ref=str(run1.id)),
        RunGraphOutcome(RunGraphOutcomeKind.SUCCEEDED, result_ref=str(run2.id)),
    ]
    assert knowledge.bindings == [
        ("PRJ-RETAIL-ALPHA", "dataset-a"),
        ("PRJ-RETAIL-ALPHA", "dataset-b"),
        ("PRJ-RETAIL-ALPHA", "dataset-a"),
        ("PRJ-RETAIL-ALPHA", "dataset-b"),
    ]


@pytest.mark.asyncio
async def test_qa_executor_rejects_resume_without_touching_session() -> None:
    factory = RecordingSessionFactory()
    llm = FakeStructuredLLM()
    executor = build_production_qa_executor(
        settings=settings(),
        session_factory=factory,  # type: ignore[arg-type]
        saver=object(),
        knowledge=BindingKnowledge(),  # type: ignore[arg-type]
        llm=llm,
        llm_usage=llm,
    )

    with pytest.raises(RuntimeError, match="QA runs do not support resume"):
        await executor.resume(run_record(), {"action": "confirm"})

    assert factory.sessions == []
