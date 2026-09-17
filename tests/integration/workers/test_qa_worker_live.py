from __future__ import annotations

import asyncio
import contextlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select
from tests.fakes.knowledge import FakeKnowledgePort

from project_agent.agent.checkpoint import async_postgres_saver
from project_agent.application.ports.job_queue import EnqueueJobRequest, JobState
from project_agent.application.ports.knowledge import (
    DeleteKnowledgeDocumentRequest,
    EnsureKnowledgeSpaceRequest,
    IngestionState,
    KnowledgeIngestionRequest,
)
from project_agent.application.ports.object_store import ObjectPayload
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
from project_agent.infrastructure.llm.adapter import (
    OpenAICompatibleStructuredLLMAdapter,
    StructuredLLMRetryPolicy,
)
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.client import RagflowRetryPolicy
from project_agent.runtime.qa import build_production_qa_executor
from project_agent.runtime.worker import build_worker_runtime
from project_agent.workers.handlers import EXECUTE_AGENT_RUN, HandlerRegistry
from project_agent.workers.main import BackgroundWorker, WorkerSettings
from project_agent.workers.run_execution import ExecuteAgentRunHandler


@dataclass(frozen=True, slots=True)
class SeededRun:
    project_id: UUID
    thread_id: UUID
    run_id: UUID
    job_id: str
    project_code: str
    dataset_id: str
    document_id: UUID | None = None
    version_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class LiveSeed:
    client_id: UUID
    user_id: UUID
    alpha: SeededRun
    beta: SeededRun
    prompt_created: bool


class LiveObjectStore:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self._payloads = payloads

    async def get(self, object_key: str) -> ObjectPayload:
        data = self._payloads[object_key]
        return ObjectPayload(
            object_key=object_key,
            data=data,
            mime_type="text/plain",
            sha256=sha256(data).hexdigest(),
        )


class AuthorizedFakeKnowledge(FakeKnowledgePort):
    def __init__(self) -> None:
        super().__init__()
        self._bindings: dict[str, str] = {}

    def bind_authorized_space(self, *, project_id: str, dataset_id: str) -> None:
        existing = self._bindings.get(dataset_id)
        if existing is not None and existing != project_id:
            raise RuntimeError("fake dataset binding collision")
        self._bindings[dataset_id] = project_id

    async def retrieve(self, request):  # type: ignore[no-untyped-def]
        for dataset_id in request.knowledge_space_ids:
            if self._bindings.get(dataset_id) != request.project_id:
                raise RuntimeError("retrieval used an unbound dataset")
        return await super().retrieve(request)


def _enabled(name: str) -> bool:
    return os.getenv(name) == "1"


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        pytest.fail(f"{name} is required for the enabled WS4 live gate")
    return value.strip()


def _live_settings() -> Settings:
    return Settings(
        app_env="development",
        database_url=_required_env("DATABASE_URL"),
        local_storage_root=Path("./data"),
        ragflow_base_url=_required_env("RAGFLOW_BASE_URL"),
        ragflow_api_key=SecretStr(_required_env("RAGFLOW_API_KEY")),
        ragflow_expected_version=os.getenv("RAGFLOW_EXPECTED_VERSION", "live"),
        ragflow_embedding_model=os.getenv("RAGFLOW_EMBEDDING_MODEL") or None,
        ragflow_chunk_method=os.getenv("RAGFLOW_CHUNK_METHOD", "naive"),
        ragflow_request_timeout_seconds=float(
            os.getenv("RAGFLOW_REQUEST_TIMEOUT_SECONDS", "30")
        ),
        ragflow_max_attempts=int(os.getenv("RAGFLOW_MAX_ATTEMPTS", "3")),
        llm_base_url=_required_env("LLM_BASE_URL"),
        llm_api_key=SecretStr(_required_env("LLM_API_KEY")),
        llm_model_alias=_required_env("LLM_MODEL_ALIAS"),
        llm_request_timeout_seconds=float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "30")),
        llm_max_attempts=int(os.getenv("LLM_MAX_ATTEMPTS", "3")),
        llm_request_capacity=int(os.getenv("LLM_REQUEST_CAPACITY", "10")),
        llm_token_capacity=int(os.getenv("LLM_TOKEN_CAPACITY", "100000")),
        retention_sweep_enabled=False,
        worker_concurrency=1,
        worker_claim_limit=1,
        worker_heartbeat_seconds=60,
        worker_poll_seconds=0.01,
        worker_retry_base_seconds=0,
        worker_retry_max_seconds=0,
    )


async def _wait_for_ingestion(adapter: RagflowAdapter, job_id: str) -> None:
    for _ in range(120):
        status = await adapter.get_ingestion_status(job_id)
        if status.state is IngestionState.SUCCEEDED:
            return
        if status.state is IngestionState.FAILED:
            pytest.fail(f"RAGFlow parsing failed: {status.error_code}")
        await asyncio.sleep(1)
    pytest.fail("RAGFlow parsing did not finish within 120 seconds")


async def _seed_live_database(
    factory,  # type: ignore[no-untyped-def]
    *,
    alpha_code: str,
    alpha_dataset: str,
    alpha_version_id: UUID,
    beta_code: str,
    beta_dataset: str,
    alpha_marker: str,
) -> LiveSeed:
    company_id = uuid4()
    client_id = uuid4()
    user_id = uuid4()
    manager_id = uuid4()
    alpha_project_id = uuid4()
    beta_project_id = uuid4()
    alpha_thread_id = uuid4()
    beta_thread_id = uuid4()
    alpha_run_id = uuid4()
    beta_run_id = uuid4()
    alpha_document_id = uuid4()
    prompt_created = False

    async with factory() as session:
        session.add(ClientModel(id=client_id, company_id=company_id, name="WS4 Live Client"))
        session.add_all(
            [
                ProjectModel(
                    id=alpha_project_id,
                    company_id=company_id,
                    client_id=client_id,
                    code=alpha_code,
                    name="WS4 Live Alpha",
                    manager_id=manager_id,
                ),
                ProjectModel(
                    id=beta_project_id,
                    company_id=company_id,
                    client_id=client_id,
                    code=beta_code,
                    name="WS4 Live Empty Beta",
                    manager_id=manager_id,
                ),
            ]
        )
        await session.flush()

        valid_from = datetime.now(UTC) - timedelta(minutes=5)
        session.add_all(
            [
                ProjectMembershipModel(
                    project_id=alpha_project_id,
                    user_id=user_id,
                    role=ProjectRole.VIEWER.value,
                    valid_from=valid_from,
                    valid_to=None,
                ),
                ProjectMembershipModel(
                    project_id=beta_project_id,
                    user_id=user_id,
                    role=ProjectRole.VIEWER.value,
                    valid_from=valid_from,
                    valid_to=None,
                ),
                ProjectKnowledgeSpaceModel(
                    project_id=alpha_project_id,
                    provider="ragflow",
                    external_space_id=alpha_dataset,
                    status="active",
                ),
                ProjectKnowledgeSpaceModel(
                    project_id=beta_project_id,
                    provider="ragflow",
                    external_space_id=beta_dataset,
                    status="active",
                ),
                DocumentModel(
                    id=alpha_document_id,
                    company_id=company_id,
                    project_id=alpha_project_id,
                    document_category=DocumentCategory.APPROVED_DESIGN.value,
                    title="WS4 Live Approved Design",
                    owner_user_id=user_id,
                ),
            ]
        )
        await session.flush()

        session.add(
            DocumentVersionModel(
                id=alpha_version_id,
                document_id=alpha_document_id,
                version_no=1,
                version_label="v1-live",
                authority_level=AuthorityLevel.APPROVED_DESIGN.value,
                lifecycle_status=DocumentLifecycleStatus.PUBLISHED.value,
                source_uri="objects/ws4-live-alpha.txt",
                content_hash=sha256(alpha_marker.encode()).hexdigest(),
                published_at=datetime.now(UTC),
                created_by=user_id,
            )
        )
        session.add_all(
            [
                ThreadModel(
                    id=alpha_thread_id,
                    company_id=company_id,
                    project_id=alpha_project_id,
                    user_id=user_id,
                ),
                ThreadModel(
                    id=beta_thread_id,
                    company_id=company_id,
                    project_id=beta_project_id,
                    user_id=user_id,
                ),
            ]
        )
        await session.flush()

        session.add_all(
            [
                AgentRunModel(
                    id=alpha_run_id,
                    thread_id=alpha_thread_id,
                    company_id=company_id,
                    project_id=alpha_project_id,
                    user_id=user_id,
                    business_mode=RunBusinessMode.QA.value,
                    status=RunStatus.QUEUED.value,
                    started_at=None,
                    finished_at=None,
                ),
                AgentRunModel(
                    id=beta_run_id,
                    thread_id=beta_thread_id,
                    company_id=company_id,
                    project_id=beta_project_id,
                    user_id=user_id,
                    business_mode=RunBusinessMode.QA.value,
                    status=RunStatus.QUEUED.value,
                    started_at=None,
                    finished_at=None,
                ),
            ]
        )
        await session.flush()

        run_repo = SqlAlchemyRunRepository(session)
        await run_repo.append_event(
            run_id=alpha_run_id,
            event_type=AgentEventType.RUN_QUEUED,
            payload={
                "query_text": (
                    "What exact marker does the approved design require "
                    "for WS4 live acceptance?"
                )
            },
        )
        await run_repo.append_event(
            run_id=beta_run_id,
            event_type=AgentEventType.RUN_QUEUED,
            payload={
                "query_text": "What approved empty-beta acceptance marker is documented?"
            },
        )
        existing_prompt = await session.scalar(
            select(SystemConfigModel.id).where(
                SystemConfigModel.config_key == "prompt.qa.answer",
                SystemConfigModel.enabled.is_(True),
            )
        )
        if existing_prompt is None:
            content = (
                "Answer only from governed project evidence. "
                "Every factual claim must cite the supplied Evidence IDs."
            )
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
        alpha_job = await jobs.enqueue(
            EnqueueJobRequest(
                job_type=RunJobType.EXECUTE.value,
                aggregate_id=str(alpha_run_id),
                max_attempts=1,
            )
        )
        beta_job = await jobs.enqueue(
            EnqueueJobRequest(
                job_type=RunJobType.EXECUTE.value,
                aggregate_id=str(beta_run_id),
                max_attempts=1,
            )
        )
        await session.commit()

    return LiveSeed(
        client_id=client_id,
        user_id=user_id,
        alpha=SeededRun(
            project_id=alpha_project_id,
            thread_id=alpha_thread_id,
            run_id=alpha_run_id,
            job_id=alpha_job.job_id,
            project_code=alpha_code,
            dataset_id=alpha_dataset,
            document_id=alpha_document_id,
            version_id=alpha_version_id,
        ),
        beta=SeededRun(
            project_id=beta_project_id,
            thread_id=beta_thread_id,
            run_id=beta_run_id,
            job_id=beta_job.job_id,
            project_code=beta_code,
            dataset_id=beta_dataset,
        ),
        prompt_created=prompt_created,
    )


async def _cleanup_seed(factory, seed: LiveSeed) -> None:  # type: ignore[no-untyped-def]
    run_ids = (seed.alpha.run_id, seed.beta.run_id)
    project_ids = (seed.alpha.project_id, seed.beta.project_id)
    thread_ids = (seed.alpha.thread_id, seed.beta.thread_id)
    job_ids = (UUID(seed.alpha.job_id), UUID(seed.beta.job_id))
    async with factory() as session:
        answer_ids = select(AnswerModel.id).where(AnswerModel.run_id.in_(run_ids))
        bundle_ids = select(EvidenceBundleModel.id).where(EvidenceBundleModel.run_id.in_(run_ids))
        await session.execute(delete(CitationModel).where(CitationModel.answer_id.in_(answer_ids)))
        await session.execute(delete(AnswerModel).where(AnswerModel.run_id.in_(run_ids)))
        await session.execute(
            delete(EvidenceSnapshotModel).where(EvidenceSnapshotModel.bundle_id.in_(bundle_ids))
        )
        await session.execute(
            delete(EvidenceBundleModel).where(EvidenceBundleModel.run_id.in_(run_ids))
        )
        await session.execute(delete(BackgroundJobModel).where(BackgroundJobModel.id.in_(job_ids)))
        await session.execute(delete(AgentEventModel).where(AgentEventModel.run_id.in_(run_ids)))
        await session.execute(delete(AgentRunModel).where(AgentRunModel.id.in_(run_ids)))
        await session.execute(delete(ThreadModel).where(ThreadModel.id.in_(thread_ids)))
        if seed.alpha.version_id is not None:
            await session.execute(
                delete(DocumentVersionModel).where(DocumentVersionModel.id == seed.alpha.version_id)
            )
        if seed.alpha.document_id is not None:
            await session.execute(
                delete(DocumentModel).where(DocumentModel.id == seed.alpha.document_id)
            )
        await session.execute(
            delete(ProjectKnowledgeSpaceModel).where(
                ProjectKnowledgeSpaceModel.project_id.in_(project_ids)
            )
        )
        await session.execute(
            delete(ProjectMembershipModel).where(ProjectMembershipModel.project_id.in_(project_ids))
        )
        await session.execute(delete(ProjectModel).where(ProjectModel.id.in_(project_ids)))
        await session.execute(delete(ClientModel).where(ClientModel.id == seed.client_id))
        if seed.prompt_created:
            await session.execute(
                delete(SystemConfigModel).where(
                    SystemConfigModel.config_key == "prompt.qa.answer",
                    SystemConfigModel.version == 1,
                    SystemConfigModel.updated_by == seed.user_id,
                )
            )
        await session.commit()


async def _assert_answered_live_run(
    factory,  # type: ignore[no-untyped-def]
    seeded: SeededRun,
    marker: str,
) -> None:
    async with factory() as session:
        run = await session.get(AgentRunModel, seeded.run_id)
        answer = await session.scalar(
            select(AnswerModel).where(AnswerModel.run_id == seeded.run_id)
        )
        bundles = select(EvidenceBundleModel.id).where(EvidenceBundleModel.run_id == seeded.run_id)
        evidence = (
            await session.scalars(
                select(EvidenceSnapshotModel).where(EvidenceSnapshotModel.bundle_id.in_(bundles))
            )
        ).all()
        event_rows = (
            await session.scalars(
                select(AgentEventModel)
                .where(AgentEventModel.run_id == seeded.run_id)
                .order_by(AgentEventModel.sequence_no)
            )
        ).all()
        artifact_diagnostics: list[str] = []
        for event in event_rows:
            if event.event_type != AgentEventType.ARTIFACT_AVAILABLE.value:
                continue
            payload = event.payload_json
            if not isinstance(payload, dict):
                continue
            artifact_type = payload.get("artifact_type")
            if artifact_type not in {"RETRIEVAL_GRADE", "CITATION_GUARD"}:
                continue
            artifact_diagnostics.append(
                f"{artifact_type}="
                + json.dumps(payload.get("artifact"), ensure_ascii=False, sort_keys=True)
            )

        refusal_reason = answer.refusal_reason if answer is not None else None
        diagnostic = (
            f"run_status={run.status if run is not None else None}; "
            f"refusal_reason={refusal_reason}; "
            f"retrieval_rounds={run.retrieval_rounds if run is not None else None}; "
            f"evidence_count={len(evidence)}; "
            f"artifacts={artifact_diagnostics}"
        )
        assert run is not None and run.status == RunStatus.SUCCEEDED.value, diagnostic
        assert run.model_alias == _required_env("LLM_MODEL_ALIAS")
        assert run.prompt_version is not None
        assert run.prompt_content_hash is not None
        assert 1 <= run.retrieval_rounds <= 2
        assert run.total_tokens == run.input_tokens + run.output_tokens
        assert run.total_tokens > 0
        assert answer is not None and answer.refusal_reason is None
        assert marker in answer.answer_text
        assert evidence
        assert all(item.project_id == seeded.project_id for item in evidence)
        assert all(
            item.metadata_json.get("project_code") == seeded.project_code
            for item in evidence
        )
        citations = (
            await session.scalars(
                select(CitationModel).where(CitationModel.answer_id == answer.id)
            )
        ).all()
        assert citations
        evidence_ids = {item.id for item in evidence}
        assert all(citation.evidence_snapshot_id in evidence_ids for citation in citations)


async def _assert_refused_live_run(
    factory,  # type: ignore[no-untyped-def]
    seeded: SeededRun,
) -> None:
    async with factory() as session:
        run = await session.get(AgentRunModel, seeded.run_id)
        answer = await session.scalar(
            select(AnswerModel).where(AnswerModel.run_id == seeded.run_id)
        )
        assert run is not None and run.status == RunStatus.REFUSED.value
        # Beta intentionally has no authorized DocumentVersion rows. The access policy
        # must short-circuit before any RAGFlow retrieval or LLM grading/answer call.
        assert run.retrieval_rounds == 0
        assert run.input_tokens == 0
        assert run.output_tokens == 0
        assert run.total_tokens == 0
        assert answer is not None
        assert answer.refusal_reason == "NO_AUTHORIZED_EVIDENCE"
        citations = (
            await session.scalars(
                select(CitationModel).where(CitationModel.answer_id == answer.id)
            )
        ).all()
        assert citations == []


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (
        _enabled("RUN_POSTGRES_INTEGRATION")
        and _enabled("RUN_RAGFLOW_INTEGRATION")
        and _enabled("RUN_LLM_INTEGRATION")
    ),
    reason=(
        "set RUN_POSTGRES_INTEGRATION=1, RUN_RAGFLOW_INTEGRATION=1, "
        "and RUN_LLM_INTEGRATION=1 for the complete WS4 live QA gate"
    ),
)
async def test_real_worker_answers_and_refuses_with_bounded_project_scoped_evidence() -> None:
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.postgres.aio")
    settings = _live_settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    suffix = uuid4().hex[:10]
    alpha_code = f"WS4-LIVE-ALPHA-{suffix}"
    beta_code = f"WS4-LIVE-BETA-{suffix}"
    alpha_marker = f"ALPHA_ONLY_{suffix}"
    alpha_version_id = uuid4()
    store = LiveObjectStore(
        {
            "alpha": (
                "The approved design requires the exact marker "
                f"{alpha_marker} for WS4 live acceptance. No other marker is approved."
            ).encode()
        }
    )
    seed: LiveSeed | None = None
    alpha_dataset_id: str | None = None

    try:
        async with httpx.AsyncClient(
            base_url=settings.ragflow_base_url,
            timeout=settings.ragflow_request_timeout_seconds,
        ) as ragflow_http:
            seed_adapter = RagflowAdapter.from_http_client(
                ragflow_http,
                api_key=settings.ragflow_api_key.get_secret_value(),
                object_store=store,
                embedding_model=settings.ragflow_embedding_model,
                chunk_method=settings.ragflow_chunk_method,
                retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
            )
            alpha_space = await seed_adapter.ensure_space(
                EnsureKnowledgeSpaceRequest(alpha_code, f"ws4-live-alpha-{suffix}")
            )
            alpha_dataset_id = alpha_space.knowledge_space_id
            beta_space = await seed_adapter.ensure_space(
                EnsureKnowledgeSpaceRequest(beta_code, f"ws4-live-beta-empty-{suffix}")
            )
            receipt = await seed_adapter.ingest(
                KnowledgeIngestionRequest(
                    project_id=alpha_code,
                    knowledge_space_id=alpha_space.knowledge_space_id,
                    document_version_id=str(alpha_version_id),
                    object_key="alpha",
                    metadata={
                        "filename": f"ws4-live-alpha-{suffix}.txt",
                        "section": "WS4 live acceptance",
                    },
                )
            )
            await _wait_for_ingestion(seed_adapter, receipt.ingestion_job_id)
            seed = await _seed_live_database(
                factory,
                alpha_code=alpha_code,
                alpha_dataset=alpha_space.knowledge_space_id,
                alpha_version_id=alpha_version_id,
                beta_code=beta_code,
                beta_dataset=beta_space.knowledge_space_id,
                alpha_marker=alpha_marker,
            )

            async with build_worker_runtime(settings) as runtime:
                assert await runtime.worker.run_once() == 1
                assert await runtime.worker.run_once() == 1
                alpha_job = await runtime.queue.get(seed.alpha.job_id)
                beta_job = await runtime.queue.get(seed.beta.job_id)
                assert alpha_job is not None and alpha_job.state is JobState.SUCCEEDED
                assert beta_job is not None and beta_job.state is JobState.SUCCEEDED

            await _assert_answered_live_run(factory, seed.alpha, alpha_marker)
            await _assert_refused_live_run(factory, seed.beta)

    finally:
        if seed is not None:
            async with async_postgres_saver(settings.database_url) as saver:
                await saver.adelete_thread(str(seed.alpha.thread_id))
                await saver.adelete_thread(str(seed.beta.thread_id))
            await _cleanup_seed(factory, seed)
        if alpha_dataset_id is not None:
            with contextlib.suppress(Exception):
                async with httpx.AsyncClient(
                    base_url=settings.ragflow_base_url,
                    timeout=settings.ragflow_request_timeout_seconds,
                ) as cleanup_http:
                    cleanup_adapter = RagflowAdapter.from_http_client(
                        cleanup_http,
                        api_key=settings.ragflow_api_key.get_secret_value(),
                    )
                    await cleanup_adapter.delete_document(
                        DeleteKnowledgeDocumentRequest(
                            alpha_code,
                            str(alpha_version_id),
                            alpha_dataset_id,
                        )
                    )
        await engine.dispose()


@dataclass(frozen=True, slots=True)
class FailureSeed:
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


async def _seed_failure_case(factory) -> FailureSeed:  # type: ignore[no-untyped-def]
    company_id = uuid4()
    client_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    manager_id = uuid4()
    thread_id = uuid4()
    run_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    project_code = f"WS4-FAIL-{project_id.hex[:10]}"
    dataset_id = f"ws4-fail-dataset-{project_id.hex[:10]}"
    prompt_created = False

    async with factory() as session:
        session.add(ClientModel(id=client_id, company_id=company_id, name="WS4 Failure Client"))
        session.add(
            ProjectModel(
                id=project_id,
                company_id=company_id,
                client_id=client_id,
                code=project_code,
                name="WS4 Failure Project",
                manager_id=manager_id,
            )
        )
        await session.flush()
        session.add_all(
            [
                ProjectMembershipModel(
                    project_id=project_id,
                    user_id=user_id,
                    role=ProjectRole.VIEWER.value,
                    valid_from=datetime.now(UTC) - timedelta(minutes=5),
                    valid_to=None,
                ),
                ProjectKnowledgeSpaceModel(
                    project_id=project_id,
                    provider="ragflow",
                    external_space_id=dataset_id,
                    status="active",
                ),
                DocumentModel(
                    id=document_id,
                    company_id=company_id,
                    project_id=project_id,
                    document_category=DocumentCategory.APPROVED_DESIGN.value,
                    title="WS4 Failure Approved Design",
                    owner_user_id=user_id,
                ),
            ]
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
                source_uri="objects/ws4-failure",
                content_hash="ws4-failure-content-hash",
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
            payload={"query_text": "What does the approved failure fixture say?"},
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
        queued = await SqlAlchemySessionJobEnqueuer(session).enqueue(
            EnqueueJobRequest(
                job_type=RunJobType.EXECUTE.value,
                aggregate_id=str(run_id),
                max_attempts=1,
            )
        )
        await session.commit()

    return FailureSeed(
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


async def _cleanup_failure_case(factory, seed: FailureSeed) -> None:  # type: ignore[no-untyped-def]
    async with factory() as session:
        answer_ids = select(AnswerModel.id).where(AnswerModel.run_id == seed.run_id)
        bundle_ids = select(EvidenceBundleModel.id).where(EvidenceBundleModel.run_id == seed.run_id)
        await session.execute(delete(CitationModel).where(CitationModel.answer_id.in_(answer_ids)))
        await session.execute(delete(AnswerModel).where(AnswerModel.run_id == seed.run_id))
        await session.execute(
            delete(EvidenceSnapshotModel).where(EvidenceSnapshotModel.bundle_id.in_(bundle_ids))
        )
        await session.execute(
            delete(EvidenceBundleModel).where(EvidenceBundleModel.run_id == seed.run_id)
        )
        await session.execute(
            delete(BackgroundJobModel).where(BackgroundJobModel.id == UUID(seed.job_id))
        )
        await session.execute(delete(AgentEventModel).where(AgentEventModel.run_id == seed.run_id))
        await session.execute(delete(AgentRunModel).where(AgentRunModel.id == seed.run_id))
        await session.execute(delete(ThreadModel).where(ThreadModel.id == seed.thread_id))
        await session.execute(
            delete(DocumentVersionModel).where(DocumentVersionModel.id == seed.version_id)
        )
        await session.execute(delete(DocumentModel).where(DocumentModel.id == seed.document_id))
        await session.execute(
            delete(ProjectKnowledgeSpaceModel).where(
                ProjectKnowledgeSpaceModel.project_id == seed.project_id
            )
        )
        await session.execute(
            delete(ProjectMembershipModel).where(
                ProjectMembershipModel.project_id == seed.project_id
            )
        )
        await session.execute(delete(ProjectModel).where(ProjectModel.id == seed.project_id))
        await session.execute(delete(ClientModel).where(ClientModel.id == seed.client_id))
        if seed.prompt_created:
            await session.execute(
                delete(SystemConfigModel).where(
                    SystemConfigModel.config_key == "prompt.qa.answer",
                    SystemConfigModel.version == 1,
                    SystemConfigModel.updated_by == seed.user_id,
                )
            )
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _enabled("RUN_POSTGRES_INTEGRATION"),
    reason="set RUN_POSTGRES_INTEGRATION=1 for the WS4 provider-failure Worker gate",
)
async def test_provider_failure_is_sanitized_and_projected_by_existing_worker_semantics() -> None:
    pytest.importorskip("langgraph")
    pytest.importorskip("langgraph.checkpoint.postgres.aio")
    database_url = _required_env("DATABASE_URL")
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    queue = PostgresJobQueue(factory, retry_base_seconds=0, retry_max_seconds=0)
    seed = await _seed_failure_case(factory)
    knowledge = AuthorizedFakeKnowledge()
    knowledge.add_chunk(
        project_id=seed.project_code,
        document_version_id=str(seed.version_id),
        content="The failure fixture has authorized evidence before the LLM call.",
        score=0.99,
        knowledge_space_id=seed.dataset_id,
        provider_ref="ws4-failure-chunk",
        section="Failure projection",
    )
    secret = "ws4-super-secret-provider-key"

    def failing_provider(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {secret}"
        return httpx.Response(500, json={"error": "provider failed"})

    try:
        async with (
            httpx.AsyncClient(
                base_url="https://llm.failure.test/v1/",
                transport=httpx.MockTransport(failing_provider),
            ) as llm_http,
            async_postgres_saver(database_url) as saver,
        ):
            llm = OpenAICompatibleStructuredLLMAdapter(
                llm_http,
                api_key=secret,
                retry_policy=StructuredLLMRetryPolicy(max_attempts=1),
            )
            settings = Settings(
                app_env="development",
                database_url=database_url,
                local_storage_root=Path("./data"),
                ragflow_base_url="http://ragflow.invalid",
                ragflow_api_key=SecretStr("fake-ragflow"),
                ragflow_expected_version="test",
                llm_base_url="https://llm.failure.test/v1/",
                llm_api_key=SecretStr(secret),
                llm_model_alias="ws4-failure-model",
                llm_request_capacity=10,
                llm_token_capacity=100_000,
            )
            executor = build_production_qa_executor(
                settings=settings,
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
                worker_id=f"ws4-provider-failure-{uuid4()}",
                settings=WorkerSettings(
                    concurrency=1,
                    claim_limit=1,
                    heartbeat_seconds=60,
                    poll_seconds=0.01,
                ),
            )
            assert await worker.run_once() == 1

        job = await queue.get(seed.job_id)
        async with factory() as session:
            run = await session.get(AgentRunModel, seed.run_id)
            events = (
                await session.scalars(
                    select(AgentEventModel)
                    .where(AgentEventModel.run_id == seed.run_id)
                    .order_by(AgentEventModel.sequence_no)
                )
            ).all()
            assert job is not None and job.state is JobState.FAILED
            assert job.last_error_code == "StructuredLLMHTTPError"
            assert run is not None and run.status == RunStatus.FAILED.value
            failed = [row for row in events if row.event_type == AgentEventType.RUN_FAILED.value]
            assert len(failed) == 1
            assert failed[0].payload_json == {"error_code": "StructuredLLMHTTPError"}
            persisted = json.dumps(
                {
                    "job_error": job.last_error_code,
                    "events": [row.payload_json for row in events],
                },
                sort_keys=True,
            )
            assert secret not in persisted
            assert "Authorization" not in persisted
    finally:
        async with async_postgres_saver(database_url) as saver:
            await saver.adelete_thread(str(seed.thread_id))
        await _cleanup_failure_case(factory, seed)
        await engine.dispose()
