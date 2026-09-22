from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.llm import FakeStructuredLLM

from project_agent.agent.checkpoint import async_postgres_saver
from project_agent.application.ports.run_graph import RunGraphOutcomeKind
from project_agent.config import Settings
from project_agent.domain.enums import (
    AuthorityLevel,
    DocumentCategory,
    DocumentLifecycleStatus,
    ProjectRole,
)
from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunRecord, RunStatus
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    AnswerModel,
    CitationModel,
    ClientModel,
    DocumentModel,
    DocumentVersionModel,
    EvidenceBundleModel,
    EvidenceSnapshotModel,
    ProjectKnowledgeSpaceModel,
    ProjectMembershipModel,
    ProjectModel,
    SystemConfigModel,
    ThreadModel,
)
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.runtime.qa import build_production_qa_executor

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL QA runtime gate",
)


class AuthorizedFakeKnowledge(FakeKnowledgePort):
    def __init__(self) -> None:
        super().__init__()
        self.bindings: dict[str, str] = {}

    def bind_authorized_space(self, *, project_id: str, dataset_id: str) -> None:
        existing = self.bindings.get(dataset_id)
        if existing is not None and existing != project_id:
            raise RuntimeError("fake dataset binding collision")
        self.bindings[dataset_id] = project_id

    async def retrieve(self, request):  # type: ignore[no-untyped-def]
        for dataset_id in request.knowledge_space_ids:
            if self.bindings.get(dataset_id) != request.project_id:
                raise RuntimeError("retrieval used an unbound dataset")
        return await super().retrieve(request)


def _settings(database_url: str) -> Settings:
    return Settings(
        app_env="development",
        database_url=database_url,
        local_storage_root=Path("./data"),
        ragflow_base_url="http://ragflow.invalid",
        ragflow_api_key=SecretStr("fake-ragflow"),
        ragflow_expected_version="test",
        llm_base_url="http://llm.invalid/v1",
        llm_api_key=SecretStr("fake-llm"),
        llm_model_alias="qa-live-fake",
        llm_request_capacity=10,
        llm_token_capacity=100_000,
    )


@pytest.mark.asyncio
async def test_production_qa_executor_persists_answer_citations_and_telemetry() -> None:
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.postgres.aio")

    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    company_id = uuid4()
    client_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    manager_id = uuid4()
    thread_id = uuid4()
    run_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    project_code = f"WS4-QA-{project_id.hex[:10]}"
    dataset_id = f"ws4-dataset-{project_id.hex[:10]}"
    prompt_created = False

    try:
        async with factory() as session:
            session.add(ClientModel(id=client_id, company_id=company_id, name="WS4 QA Client"))
            session.add(
                ProjectModel(
                    id=project_id,
                    company_id=company_id,
                    client_id=client_id,
                    code=project_code,
                    name="WS4 QA Project",
                    manager_id=manager_id,
                )
            )
            await session.flush()

            session.add(
                ProjectMembershipModel(
                    project_id=project_id,
                    user_id=user_id,
                    role=ProjectRole.VIEWER.value,
                    valid_from=datetime.now(UTC) - timedelta(minutes=5),
                    valid_to=None,
                )
            )
            session.add(
                ProjectKnowledgeSpaceModel(
                    project_id=project_id,
                    provider="ragflow",
                    external_space_id=dataset_id,
                    status="active",
                )
            )
            session.add(
                DocumentModel(
                    id=document_id,
                    company_id=company_id,
                    project_id=project_id,
                    document_category=DocumentCategory.APPROVED_DESIGN.value,
                    title="WS4 Approved Design",
                    owner_user_id=user_id,
                )
            )
            await session.flush()

            session.add(
                DocumentVersionModel(
                    id=version_id,
                    document_id=document_id,
                    version_no=1,
                    version_label="v1",
                    authority_level=AuthorityLevel.APPROVED_DESIGN.value,
                    lifecycle_status=DocumentLifecycleStatus.PUBLISHED.value,
                    source_uri="objects/ws4-design",
                    content_hash="ws4-content-hash",
                    published_at=datetime.now(UTC),
                    created_by=user_id,
                )
            )
            session.add(
                ThreadModel(
                    id=thread_id,
                    company_id=company_id,
                    project_id=project_id,
                    user_id=user_id,
                )
            )
            await session.flush()

            session.add(
                AgentRunModel(
                    id=run_id,
                    thread_id=thread_id,
                    company_id=company_id,
                    project_id=project_id,
                    user_id=user_id,
                    business_mode=RunBusinessMode.QA.value,
                    status=RunStatus.RUNNING.value,
                    started_at=datetime.now(UTC),
                    finished_at=None,
                )
            )
            await session.flush()

            session.add(
                AgentEventModel(
                    run_id=run_id,
                    sequence_no=1,
                    event_type=AgentEventType.RUN_QUEUED.value,
                    payload_json={"query_text": "What does the approved design say?"},
                )
            )
            existing_prompt = await session.scalar(
                select(SystemConfigModel.id).where(
                    SystemConfigModel.config_key == "prompt.qa.answer",
                    SystemConfigModel.enabled.is_(True),
                )
            )
            if existing_prompt is None:
                content = "Answer only from governed project evidence."
                session.add(
                    SystemConfigModel(
                        config_key="prompt.qa.answer",
                        config_value_json={"content": content},
                        version=1,
                        content_hash=sha256(content.encode()).hexdigest(),
                        enabled=True,
                        updated_by=user_id,
                    )
                )
                prompt_created = True
            await session.commit()

        knowledge = AuthorizedFakeKnowledge()
        knowledge.add_chunk(
            project_id=project_code,
            document_version_id=str(version_id),
            content="The approved design requires bounded QA retrieval.",
            score=0.98,
            knowledge_space_id=dataset_id,
            provider_ref="chunk-ws4-1",
            section="Architecture",
        )
        llm = FakeStructuredLLM()
        llm.queue_response(
            {
                "adequate": True,
                "reason": "ADEQUATE",
                "second_round_justified": False,
                "refined_query": None,
            },
            input_tokens=12,
            output_tokens=4,
        )
        llm.queue_response(
            {
                "claims": [
                    {
                        "text": "The approved design requires bounded QA retrieval.",
                        "evidence_ids": ["E1"],
                    }
                ],
                "conflict_disclosure": None,
            },
            input_tokens=20,
            output_tokens=7,
        )
        run = RunRecord(
            id=run_id,
            thread_id=thread_id,
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
            business_mode=RunBusinessMode.QA,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
            finished_at=None,
        )

        async with async_postgres_saver(database_url) as saver:
            executor = build_production_qa_executor(
                settings=_settings(database_url),
                session_factory=factory,
                saver=saver,
                knowledge=knowledge,  # type: ignore[arg-type]
                llm=llm,
                llm_usage=llm,
            )
            outcome = await executor.execute(run)

        assert outcome.kind is RunGraphOutcomeKind.SUCCEEDED
        assert outcome.result_ref is not None
        assert knowledge.bindings == {dataset_id: project_code}

        async with factory() as session:
            stored_run = await session.get(AgentRunModel, run_id)
            answer = await session.scalar(select(AnswerModel).where(AnswerModel.run_id == run_id))
            citations = (
                await session.scalars(
                    select(CitationModel).where(CitationModel.answer_id == answer.id)
                )
            ).all() if answer is not None else []
            assert stored_run is not None
            assert answer is not None
            assert str(answer.id) == outcome.result_ref
            assert len(citations) == 1
            assert stored_run.model_alias == "qa-live-fake"
            assert stored_run.prompt_version is not None
            assert stored_run.prompt_content_hash is not None
            assert stored_run.input_tokens == 32
            assert stored_run.output_tokens == 11
            assert stored_run.total_tokens == 43
            assert stored_run.retrieval_rounds == 1
    finally:
        async with factory() as session:
            answer_ids = select(AnswerModel.id).where(AnswerModel.run_id == run_id)
            bundle_ids = select(EvidenceBundleModel.id).where(EvidenceBundleModel.run_id == run_id)
            await session.execute(
                delete(CitationModel).where(CitationModel.answer_id.in_(answer_ids))
            )
            await session.execute(delete(AnswerModel).where(AnswerModel.run_id == run_id))
            await session.execute(
                delete(EvidenceSnapshotModel).where(EvidenceSnapshotModel.bundle_id.in_(bundle_ids))
            )
            await session.execute(
                delete(EvidenceBundleModel).where(EvidenceBundleModel.run_id == run_id)
            )
            await session.execute(delete(AgentEventModel).where(AgentEventModel.run_id == run_id))
            await session.execute(delete(AgentRunModel).where(AgentRunModel.id == run_id))
            await session.execute(delete(ThreadModel).where(ThreadModel.id == thread_id))
            await session.execute(
                delete(DocumentVersionModel).where(DocumentVersionModel.id == version_id)
            )
            await session.execute(delete(DocumentModel).where(DocumentModel.id == document_id))
            await session.execute(
                delete(ProjectKnowledgeSpaceModel).where(
                    ProjectKnowledgeSpaceModel.project_id == project_id
                )
            )
            await session.execute(
                delete(ProjectMembershipModel).where(
                    ProjectMembershipModel.project_id == project_id
                )
            )
            await session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
            await session.execute(delete(ClientModel).where(ClientModel.id == client_id))
            if prompt_created:
                await session.execute(
                    delete(SystemConfigModel).where(
                        SystemConfigModel.config_key == "prompt.qa.answer",
                        SystemConfigModel.version == 1,
                        SystemConfigModel.updated_by == user_id,
                    )
                )
            await session.commit()
        await engine.dispose()
