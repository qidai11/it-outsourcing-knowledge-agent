from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.llm import FakeStructuredLLM

from project_agent.agent.checkpoint import async_postgres_saver
from project_agent.application.ports.job_queue import EnqueueJobRequest, JobState
from project_agent.config import Settings
from project_agent.domain.enums import (
    AuthorityLevel,
    DocumentCategory,
    DocumentLifecycleStatus,
    ProjectRole,
)
from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunJobType, RunStatus
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    AnswerModel,
    BackgroundJobModel,
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
from project_agent.infrastructure.db.repositories.runs import SqlAlchemyRunRepository
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.jobs.postgres import (
    PostgresJobQueue,
    SqlAlchemySessionJobEnqueuer,
)
from project_agent.runtime.qa import build_production_qa_executor
from project_agent.workers.handlers import EXECUTE_AGENT_RUN, HandlerRegistry
from project_agent.workers.main import BackgroundWorker, WorkerSettings
from project_agent.workers.run_execution import ExecuteAgentRunHandler

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL QA Worker gate",
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


@dataclass(frozen=True, slots=True)
class SeededQA:
    client_id: UUID
    project_id: UUID
    user_id: UUID
    thread_id: UUID
    run_id: UUID
    document_id: UUID
    version_id: UUID
    job_id: str
    project_code: str
    dataset_id: str
    prompt_created: bool


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
        llm_model_alias="qa-worker-fake",
        llm_request_capacity=10,
        llm_token_capacity=100_000,
    )


async def _seed(factory) -> SeededQA:  # type: ignore[no-untyped-def]
    company_id = uuid4()
    client_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    manager_id = uuid4()
    thread_id = uuid4()
    run_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    project_code = f"WS4-WORKER-{project_id.hex[:10]}"
    dataset_id = f"ws4-worker-dataset-{project_id.hex[:10]}"
    prompt_created = False

    async with factory() as session:
        session.add(ClientModel(id=client_id, company_id=company_id, name="WS4 Worker Client"))
        session.add(
            ProjectModel(
                id=project_id,
                company_id=company_id,
                client_id=client_id,
                code=project_code,
                name="WS4 Worker Project",
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
                title="WS4 Worker Approved Design",
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
                source_uri="objects/ws4-worker-design",
                content_hash="ws4-worker-content-hash",
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
                status=RunStatus.QUEUED.value,
                started_at=None,
                finished_at=None,
            )
        )
        await session.flush()

        repo = SqlAlchemyRunRepository(session)
        await repo.append_event(
            run_id=run_id,
            event_type=AgentEventType.RUN_QUEUED,
            payload={"query_text": "What does the approved design require?"},
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
        jobs = SqlAlchemySessionJobEnqueuer(session)
        queued = await jobs.enqueue(
            EnqueueJobRequest(
                job_type=RunJobType.EXECUTE.value,
                aggregate_id=str(run_id),
            )
        )
        await session.commit()

    return SeededQA(
        client_id=client_id,
        project_id=project_id,
        user_id=user_id,
        thread_id=thread_id,
        run_id=run_id,
        document_id=document_id,
        version_id=version_id,
        job_id=queued.job_id,
        project_code=project_code,
        dataset_id=dataset_id,
        prompt_created=prompt_created,
    )


async def _cleanup(factory, seeded: SeededQA) -> None:  # type: ignore[no-untyped-def]
    async with factory() as session:
        answer_ids = select(AnswerModel.id).where(AnswerModel.run_id == seeded.run_id)
        bundle_ids = select(EvidenceBundleModel.id).where(
            EvidenceBundleModel.run_id == seeded.run_id
        )
        await session.execute(delete(CitationModel).where(CitationModel.answer_id.in_(answer_ids)))
        await session.execute(delete(AnswerModel).where(AnswerModel.run_id == seeded.run_id))
        await session.execute(
            delete(EvidenceSnapshotModel).where(EvidenceSnapshotModel.bundle_id.in_(bundle_ids))
        )
        await session.execute(
            delete(EvidenceBundleModel).where(EvidenceBundleModel.run_id == seeded.run_id)
        )
        await session.execute(
            delete(BackgroundJobModel).where(BackgroundJobModel.id == UUID(seeded.job_id))
        )
        await session.execute(
            delete(AgentEventModel).where(AgentEventModel.run_id == seeded.run_id)
        )
        await session.execute(delete(AgentRunModel).where(AgentRunModel.id == seeded.run_id))
        await session.execute(delete(ThreadModel).where(ThreadModel.id == seeded.thread_id))
        await session.execute(
            delete(DocumentVersionModel).where(DocumentVersionModel.id == seeded.version_id)
        )
        await session.execute(delete(DocumentModel).where(DocumentModel.id == seeded.document_id))
        await session.execute(
            delete(ProjectKnowledgeSpaceModel).where(
                ProjectKnowledgeSpaceModel.project_id == seeded.project_id
            )
        )
        await session.execute(
            delete(ProjectMembershipModel).where(
                ProjectMembershipModel.project_id == seeded.project_id
            )
        )
        await session.execute(delete(ProjectModel).where(ProjectModel.id == seeded.project_id))
        await session.execute(delete(ClientModel).where(ClientModel.id == seeded.client_id))
        if seeded.prompt_created:
            await session.execute(
                delete(SystemConfigModel).where(
                    SystemConfigModel.config_key == "prompt.qa.answer",
                    SystemConfigModel.version == 1,
                    SystemConfigModel.updated_by == seeded.user_id,
                )
            )
        await session.commit()


async def _run_worker_case(*, refusal: bool) -> tuple[RunStatus, int]:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    queue = PostgresJobQueue(factory, retry_base_seconds=0, retry_max_seconds=0)
    seeded = await _seed(factory)
    knowledge = AuthorizedFakeKnowledge()
    knowledge.add_chunk(
        project_id=seeded.project_code,
        document_version_id=str(seeded.version_id),
        content="The approved design requires bounded QA retrieval.",
        score=0.98,
        knowledge_space_id=seeded.dataset_id,
        provider_ref="worker-chunk-1",
        section="Architecture",
    )
    llm = FakeStructuredLLM()
    if refusal:
        llm.queue_response(
            {
                "adequate": False,
                "reason": "INSUFFICIENT_COVERAGE",
                "second_round_justified": True,
                "refined_query": "approved design bounded QA retrieval details",
            },
            input_tokens=8,
            output_tokens=3,
        )
        llm.queue_response(
            {
                "adequate": False,
                "reason": "INSUFFICIENT_COVERAGE",
                "second_round_justified": False,
                "refined_query": None,
            },
            input_tokens=9,
            output_tokens=3,
        )
        expected_status = RunStatus.REFUSED
    else:
        llm.queue_response(
            {
                "adequate": True,
                "reason": "ADEQUATE",
                "second_round_justified": False,
                "refined_query": None,
            },
            input_tokens=8,
            output_tokens=3,
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
            input_tokens=10,
            output_tokens=5,
        )
        expected_status = RunStatus.SUCCEEDED

    try:
        async with async_postgres_saver(database_url) as saver:
            executor = build_production_qa_executor(
                settings=_settings(database_url),
                session_factory=factory,
                saver=saver,
                knowledge=knowledge,  # type: ignore[arg-type]
                llm=llm,
                llm_usage=llm,
            )
            handlers = HandlerRegistry()
            handlers.register(EXECUTE_AGENT_RUN, ExecuteAgentRunHandler(factory, executor))
            worker = BackgroundWorker(
                queue,
                handlers,
                worker_id=f"ws4-qa-worker-{uuid4()}",
                settings=WorkerSettings(
                    concurrency=1,
                    claim_limit=1,
                    heartbeat_seconds=60,
                    poll_seconds=0.01,
                ),
            )
            assert await worker.run_once() == 1

        job = await queue.get(seeded.job_id)
        async with factory() as session:
            repo = SqlAlchemyRunRepository(session)
            run = await repo.get_run(seeded.run_id)
            events = await repo.list_events_after(
                run_id=seeded.run_id,
                after_sequence=0,
                limit=100,
            )
            db_run = await session.get(AgentRunModel, seeded.run_id)
            answer = await session.scalar(
                select(AnswerModel).where(AnswerModel.run_id == seeded.run_id)
            )
            assert job is not None and job.state is JobState.SUCCEEDED
            assert run is not None and run.status is expected_status
            assert db_run is not None
            assert answer is not None
            event_types = [event.event_type for event in events]
            assert event_types.count(AgentEventType.RUN_STARTED) == 1
            terminal_type = (
                AgentEventType.RUN_REFUSED if refusal else AgentEventType.RUN_SUCCEEDED
            )
            assert event_types.count(terminal_type) == 1
            expected_rounds = 2 if refusal else 1
            assert db_run.retrieval_rounds == expected_rounds
            assert db_run.total_tokens > 0
            if not refusal:
                citations = (
                    await session.scalars(
                        select(CitationModel).where(CitationModel.answer_id == answer.id)
                    )
                ).all()
                assert len(citations) == 1
            return run.status, db_run.retrieval_rounds
    finally:
        async with async_postgres_saver(database_url) as saver:
            await saver.adelete_thread(str(seeded.thread_id))
        await _cleanup(factory, seeded)
        await engine.dispose()


@pytest.mark.asyncio
async def test_durable_qa_worker_succeeds_with_answer_and_citation() -> None:
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.postgres.aio")
    assert await _run_worker_case(refusal=False) == (RunStatus.SUCCEEDED, 1)


@pytest.mark.asyncio
async def test_durable_qa_worker_refuses_after_exactly_two_retrieval_rounds() -> None:
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.postgres.aio")
    assert await _run_worker_case(refusal=True) == (RunStatus.REFUSED, 2)
