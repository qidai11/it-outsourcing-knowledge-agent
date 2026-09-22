from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from tests.helpers.jwt import make_hs256_token

from project_agent.agent.checkpoint import async_postgres_saver
from project_agent.application.ports.knowledge import (
    DeleteKnowledgeDocumentRequest,
    EnsureKnowledgeSpaceRequest,
    IngestionState,
    KnowledgeIngestionRequest,
)
from project_agent.application.ports.object_store import ObjectPayload
from project_agent.config import Settings, load_settings
from project_agent.domain.enums import (
    AuthorityLevel,
    DocumentCategory,
    DocumentLifecycleStatus,
    ProjectRole,
)
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    AnswerModel,
    AuditLogModel,
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
    SandboxIssueModel,
    SandboxProjectModel,
    SystemConfigModel,
    ThreadModel,
)
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.client import RagflowRetryPolicy


@dataclass(frozen=True, slots=True)
class LiveScope:
    company_id: UUID
    client_id: UUID
    project_a: UUID
    project_b: UUID
    user_a: UUID
    user_b: UUID
    project_a_code: str
    project_b_code: str
    project_a_dataset: str
    project_b_dataset: str


class _MemoryObjectStore:
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


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        pytest.fail(f"{name} is required when RUN_WS7_COMPOSE_LIVE=1")
    return value.strip()


def require_ws7_live() -> None:
    if os.getenv("RUN_WS7_COMPOSE_LIVE") != "1":
        pytest.skip("set RUN_WS7_COMPOSE_LIVE=1 for WS7 Compose live acceptance")
    for name in (
        "DATABASE_URL",
        "RAGFLOW_BASE_URL",
        "RAGFLOW_API_KEY",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL_ALIAS",
        "JWT_HS256_SECRET",
    ):
        _required_env(name)


def make_live_token(*, user_id: UUID) -> str:
    require_ws7_live()
    return make_hs256_token(
        user_id=user_id,
        secret=_required_env("JWT_HS256_SECRET"),
        issuer=os.getenv("JWT_ISSUER", "project-agent"),
        audience=os.getenv("JWT_AUDIENCE", "project-agent-api"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _settings() -> Settings:
    return load_settings()


async def _wait_for_ingestion(adapter: RagflowAdapter, job_id: str) -> None:
    for _ in range(120):
        status = await adapter.get_ingestion_status(job_id)
        if status.state is IngestionState.SUCCEEDED:
            return
        if status.state is IngestionState.FAILED:
            pytest.fail(f"RAGFlow parsing failed: {status.error_code}")
        await asyncio.sleep(1)
    pytest.fail("RAGFlow parsing did not finish within 120 seconds")


async def _create_spaces_and_ingest(
    *,
    project_a_code: str,
    project_b_code: str,
    document_version_id: UUID,
    content: str,
    prefix: str,
) -> tuple[str, str]:
    settings = _settings()
    object_key = f"{prefix}-document"
    store = _MemoryObjectStore({object_key: content.encode()})
    async with httpx.AsyncClient(
        base_url=settings.ragflow_base_url,
        timeout=settings.ragflow_request_timeout_seconds,
    ) as client:
        adapter = RagflowAdapter.from_http_client(
            client,
            api_key=settings.ragflow_api_key.get_secret_value(),
            object_store=store,
            embedding_model=settings.ragflow_embedding_model,
            chunk_method=settings.ragflow_chunk_method,
            retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
        )
        suffix = uuid4().hex[:10]
        alpha = await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest(project_a_code, f"{prefix}-alpha-{suffix}")
        )
        beta = await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest(project_b_code, f"{prefix}-beta-{suffix}")
        )
        receipt = await adapter.ingest(
            KnowledgeIngestionRequest(
                project_id=project_a_code,
                knowledge_space_id=alpha.knowledge_space_id,
                document_version_id=str(document_version_id),
                object_key=object_key,
                metadata={
                    "filename": f"{prefix}-{suffix}.txt",
                    "section": "WS7 live acceptance",
                },
            )
        )
        await _wait_for_ingestion(adapter, receipt.ingestion_job_id)
    return alpha.knowledge_space_id, beta.knowledge_space_id


async def seed_qa_scope() -> tuple[LiveScope, str]:
    require_ws7_live()
    suffix = uuid4().hex[:10]
    marker = f"WS7_ALPHA_ONLY_{suffix}"
    company_id = uuid4()
    client_id = uuid4()
    project_a = uuid4()
    project_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    version_id = uuid4()
    project_a_code = f"WS7-QA-A-{suffix}"
    project_b_code = f"WS7-QA-B-{suffix}"
    content = (
        "The approved WS7 design requires the exact acceptance marker "
        f"{marker}. This marker belongs only to the authorized alpha project."
    )
    project_a_dataset, project_b_dataset = await _create_spaces_and_ingest(
        project_a_code=project_a_code,
        project_b_code=project_b_code,
        document_version_id=version_id,
        content=content,
        prefix="ws7-qa",
    )

    settings = _settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    document_id = uuid4()
    now = datetime.now(UTC)
    try:
        async with factory() as session:
            session.add(ClientModel(id=client_id, company_id=company_id, name="WS7 QA Client"))
            session.add_all(
                [
                    ProjectModel(
                        id=project_a,
                        company_id=company_id,
                        client_id=client_id,
                        code=project_a_code,
                        name="WS7 QA Alpha",
                        manager_id=user_a,
                    ),
                    ProjectModel(
                        id=project_b,
                        company_id=company_id,
                        client_id=client_id,
                        code=project_b_code,
                        name="WS7 QA Beta",
                        manager_id=user_b,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ProjectMembershipModel(
                        project_id=project_a,
                        user_id=user_a,
                        role=ProjectRole.VIEWER.value,
                        valid_from=now - timedelta(minutes=5),
                        valid_to=None,
                    ),
                    ProjectMembershipModel(
                        project_id=project_b,
                        user_id=user_b,
                        role=ProjectRole.VIEWER.value,
                        valid_from=now - timedelta(minutes=5),
                        valid_to=None,
                    ),
                    ProjectKnowledgeSpaceModel(
                        project_id=project_a,
                        provider="ragflow",
                        external_space_id=project_a_dataset,
                        status="active",
                    ),
                    ProjectKnowledgeSpaceModel(
                        project_id=project_b,
                        provider="ragflow",
                        external_space_id=project_b_dataset,
                        status="active",
                    ),
                    DocumentModel(
                        id=document_id,
                        company_id=company_id,
                        project_id=project_a,
                        document_category=DocumentCategory.APPROVED_DESIGN.value,
                        title="WS7 approved alpha design",
                        owner_user_id=user_a,
                    ),
                ]
            )
            await session.flush()
            session.add(
                DocumentVersionModel(
                    id=version_id,
                    document_id=document_id,
                    version_no=1,
                    version_label="v1-ws7",
                    authority_level=AuthorityLevel.APPROVED_DESIGN.value,
                    lifecycle_status=DocumentLifecycleStatus.PUBLISHED.value,
                    source_uri=f"objects/ws7-qa-{suffix}.txt",
                    content_hash=sha256(content.encode()).hexdigest(),
                    published_at=now,
                    created_by=user_a,
                )
            )
            existing_prompt = await session.scalar(
                select(SystemConfigModel.id).where(
                    SystemConfigModel.config_key == "prompt.qa.answer",
                    SystemConfigModel.enabled.is_(True),
                )
            )
            if existing_prompt is None:
                current_version = await session.scalar(
                    select(func.max(SystemConfigModel.version)).where(
                        SystemConfigModel.config_key == "prompt.qa.answer"
                    )
                )
                prompt = (
                    "Answer only from governed project evidence. Every factual claim must cite "
                    "the supplied Evidence IDs."
                )
                session.add(
                    SystemConfigModel(
                        config_key="prompt.qa.answer",
                        config_value_json={"content": prompt},
                        version=int(current_version or 0) + 1,
                        content_hash=sha256(prompt.encode()).hexdigest(),
                        enabled=True,
                        updated_by=user_a,
                    )
                )
            await session.commit()
    finally:
        await engine.dispose()

    return (
        LiveScope(
            company_id=company_id,
            client_id=client_id,
            project_a=project_a,
            project_b=project_b,
            user_a=user_a,
            user_b=user_b,
            project_a_code=project_a_code,
            project_b_code=project_b_code,
            project_a_dataset=project_a_dataset,
            project_b_dataset=project_b_dataset,
        ),
        marker,
    )


async def seed_issue_scope() -> tuple[LiveScope, UUID]:
    require_ws7_live()
    suffix = uuid4().hex[:10]
    company_id = uuid4()
    client_id = uuid4()
    project_a = uuid4()
    project_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    version_id = uuid4()
    project_a_code = f"WS7-ISSUE-A-{suffix}"
    project_b_code = f"WS7-ISSUE-B-{suffix}"
    content = "ERR-IMPORT-004 acceptance failures must create one tracked sandbox issue."
    project_a_dataset, project_b_dataset = await _create_spaces_and_ingest(
        project_a_code=project_a_code,
        project_b_code=project_b_code,
        document_version_id=version_id,
        content=content,
        prefix="ws7-issue",
    )

    settings = _settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    now = datetime.now(UTC)
    document_id = uuid4()
    sandbox_project_id = uuid4()
    existing_issue_id = uuid4()
    try:
        async with factory() as session:
            session.add(ClientModel(id=client_id, company_id=company_id, name="WS7 Issue Client"))
            session.add_all(
                [
                    ProjectModel(
                        id=project_a,
                        company_id=company_id,
                        client_id=client_id,
                        code=project_a_code,
                        name="WS7 Issue Alpha",
                        phase="acceptance",
                        manager_id=user_a,
                    ),
                    ProjectModel(
                        id=project_b,
                        company_id=company_id,
                        client_id=client_id,
                        code=project_b_code,
                        name="WS7 Issue Beta",
                        phase="acceptance",
                        manager_id=user_b,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ProjectMembershipModel(
                        project_id=project_a,
                        user_id=user_a,
                        role=ProjectRole.DEVELOPER.value,
                        valid_from=now - timedelta(minutes=5),
                        valid_to=None,
                    ),
                    ProjectMembershipModel(
                        project_id=project_b,
                        user_id=user_b,
                        role=ProjectRole.DEVELOPER.value,
                        valid_from=now - timedelta(minutes=5),
                        valid_to=None,
                    ),
                    ProjectKnowledgeSpaceModel(
                        project_id=project_a,
                        provider="ragflow",
                        external_space_id=project_a_dataset,
                        status="active",
                    ),
                    ProjectKnowledgeSpaceModel(
                        project_id=project_b,
                        provider="ragflow",
                        external_space_id=project_b_dataset,
                        status="active",
                    ),
                    SandboxProjectModel(
                        id=sandbox_project_id,
                        project_id=project_a,
                        external_key=f"WS7-{project_a.hex[:8]}",
                        name="WS7 Issue Sandbox",
                    ),
                    DocumentModel(
                        id=document_id,
                        company_id=company_id,
                        project_id=project_a,
                        document_category=DocumentCategory.REQUIREMENT_BASELINE.value,
                        title="WS7 import acceptance requirement",
                        owner_user_id=user_a,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    SandboxIssueModel(
                        id=existing_issue_id,
                        project_id=project_a,
                        sandbox_project_id=sandbox_project_id,
                        issue_key=f"EXIST-{existing_issue_id.hex[:8]}",
                        title="Existing import failure",
                        description="ERR-IMPORT-004 already observed",
                        issue_type="bug",
                        priority="medium",
                        status="OPEN",
                        module="import",
                        error_code="ERR-IMPORT-004",
                        reporter_id=user_a,
                    ),
                    DocumentVersionModel(
                        id=version_id,
                        document_id=document_id,
                        version_no=1,
                        version_label="v1-ws7",
                        authority_level=AuthorityLevel.REQUIREMENT_BASELINE.value,
                        lifecycle_status=DocumentLifecycleStatus.PUBLISHED.value,
                        effective_from=date(2026, 1, 1),
                        effective_to=None,
                        source_uri=f"objects/ws7-issue-{suffix}.txt",
                        content_hash=sha256(content.encode()).hexdigest(),
                        published_at=now,
                        created_by=user_a,
                    ),
                ]
            )
            await session.commit()
    finally:
        await engine.dispose()

    return (
        LiveScope(
            company_id=company_id,
            client_id=client_id,
            project_a=project_a,
            project_b=project_b,
            user_a=user_a,
            user_b=user_b,
            project_a_code=project_a_code,
            project_b_code=project_b_code,
            project_a_dataset=project_a_dataset,
            project_b_dataset=project_b_dataset,
        ),
        version_id,
    )


async def cleanup_live_scope(scope: LiveScope) -> None:
    settings = _settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    document_refs: list[tuple[str, str, str]] = []
    thread_ids: tuple[UUID, ...] = ()
    run_ids: tuple[UUID, ...] = ()
    try:
        async with factory() as session:
            rows = (
                await session.execute(
                    select(
                        ProjectModel.code,
                        ProjectKnowledgeSpaceModel.external_space_id,
                        DocumentVersionModel.id,
                    )
                    .join(
                        ProjectKnowledgeSpaceModel,
                        ProjectKnowledgeSpaceModel.project_id == ProjectModel.id,
                    )
                    .join(DocumentModel, DocumentModel.project_id == ProjectModel.id)
                    .join(
                        DocumentVersionModel,
                        DocumentVersionModel.document_id == DocumentModel.id,
                    )
                    .where(ProjectModel.id.in_((scope.project_a, scope.project_b)))
                )
            ).all()
            document_refs = [(str(code), str(space), str(version)) for code, space, version in rows]
            thread_ids = tuple(
                (
                    await session.scalars(
                        select(ThreadModel.id).where(
                            ThreadModel.project_id.in_((scope.project_a, scope.project_b))
                        )
                    )
                ).all()
            )
            run_ids = tuple(
                (
                    await session.scalars(
                        select(AgentRunModel.id).where(
                            AgentRunModel.project_id.in_((scope.project_a, scope.project_b))
                        )
                    )
                ).all()
            )

        if document_refs:
            with contextlib.suppress(Exception):
                async with httpx.AsyncClient(
                    base_url=settings.ragflow_base_url,
                    timeout=settings.ragflow_request_timeout_seconds,
                ) as client:
                    adapter = RagflowAdapter.from_http_client(
                        client,
                        api_key=settings.ragflow_api_key.get_secret_value(),
                    )
                    for project_code, dataset_id, version_id in document_refs:
                        await adapter.delete_document(
                            DeleteKnowledgeDocumentRequest(
                                project_code,
                                version_id,
                                dataset_id,
                            )
                        )

        if thread_ids:
            with contextlib.suppress(Exception):
                async with async_postgres_saver(settings.database_url) as saver:
                    for thread_id in thread_ids:
                        await saver.adelete_thread(str(thread_id))

        async with factory() as session:
            if run_ids:
                answer_ids = select(AnswerModel.id).where(AnswerModel.run_id.in_(run_ids))
                bundle_ids = select(EvidenceBundleModel.id).where(
                    EvidenceBundleModel.run_id.in_(run_ids)
                )
                await session.execute(
                    delete(CitationModel).where(CitationModel.answer_id.in_(answer_ids))
                )
                await session.execute(delete(AnswerModel).where(AnswerModel.run_id.in_(run_ids)))
                await session.execute(
                    delete(EvidenceSnapshotModel).where(
                        EvidenceSnapshotModel.bundle_id.in_(bundle_ids)
                    )
                )
                await session.execute(
                    delete(EvidenceBundleModel).where(EvidenceBundleModel.run_id.in_(run_ids))
                )
                await session.execute(
                    delete(BackgroundJobModel).where(
                        BackgroundJobModel.aggregate_id.in_(tuple(str(item) for item in run_ids))
                    )
                )
                await session.execute(
                    delete(AgentEventModel).where(AgentEventModel.run_id.in_(run_ids))
                )
                await session.execute(delete(AgentRunModel).where(AgentRunModel.id.in_(run_ids)))
            if thread_ids:
                await session.execute(delete(ThreadModel).where(ThreadModel.id.in_(thread_ids)))
            await session.execute(
                delete(SystemConfigModel).where(
                    SystemConfigModel.config_key == "prompt.qa.answer",
                    SystemConfigModel.updated_by.in_((scope.user_a, scope.user_b)),
                )
            )
            await session.execute(
                delete(AuditLogModel).where(
                    AuditLogModel.project_id.in_((scope.project_a, scope.project_b))
                )
            )
            await session.execute(
                delete(ProjectModel).where(ProjectModel.id.in_((scope.project_a, scope.project_b)))
            )
            await session.execute(delete(ClientModel).where(ClientModel.id == scope.client_id))
            await session.commit()
    finally:
        await engine.dispose()


async def wait_for_run_status(
    client: httpx.AsyncClient,
    *,
    run_id: UUID,
    headers: dict[str, str],
    expected: set[str],
    timeout_seconds: float = 90.0,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last: dict[str, object] | None = None
    terminal = {"SUCCEEDED", "REFUSED", "CANCELLED", "FAILED"}
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/runs/{run_id}", headers=headers)
        if response.status_code != 200:
            pytest.fail(f"run poll returned {response.status_code}: {response.text}")
        body = response.json()
        last = body
        status = str(body.get("status", ""))
        if status in expected:
            return body
        if status in terminal:
            pytest.fail(f"run reached unexpected terminal status {status}: {body}")
        await asyncio.sleep(0.5)
    pytest.fail(f"run did not reach {sorted(expected)} within {timeout_seconds}s; last={last}")


@pytest.fixture
async def ws7_live_scope() -> AsyncIterator[tuple[LiveScope, str]]:
    require_ws7_live()
    scope, marker = await seed_qa_scope()
    try:
        yield scope, marker
    finally:
        await cleanup_live_scope(scope)


@pytest.fixture
async def ws7_live_issue_scope() -> AsyncIterator[tuple[LiveScope, UUID]]:
    require_ws7_live()
    scope, version_id = await seed_issue_scope()
    try:
        yield scope, version_id
    finally:
        await cleanup_live_scope(scope)
