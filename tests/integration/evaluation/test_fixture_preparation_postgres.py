"""WS8 Task 2 PostgreSQL RED against a *dedicated* evaluation database.

Test-facing, evaluation-only seam to implement in evaluation/fixtures.py:

    await prepare_v0(dataset=..., evaluation_namespace=..., session_factory=...,
                     ragflow_adapter=None) -> Mapping[str, Any]
    await cleanup_v0(evaluation_namespace=..., session_factory=...,
                     ragflow_adapter=None) -> None

Fixture state maps use the names in the frozen plan: ``project_ids``,
``user_ids``, ``membership_ids``, ``document_ids``,
``document_version_ids``, ``knowledge_space_ids``, ``sandbox_issue_ids``.
The returned state also contains ``evaluation_namespace``, ``company_id``,
``client_ids`` and the frozen ``integrity`` hashes.

No live test runs without both RUN_POSTGRES_INTEGRATION=1 and an explicit
WS8_EVAL_DATABASE_URL naming a dedicated evaluation DB.  These tests never
migrate, drop schemas or perform unrestricted table deletion.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from project_agent.evaluation.dataset import load_evaluation_dataset
from project_agent.infrastructure.db.models.schema import (
    ClientModel,
    DocumentIdentifierModel,
    DocumentModel,
    DocumentVersionModel,
    ProjectKnowledgeSpaceModel,
    ProjectMembershipModel,
    ProjectModel,
    SandboxIssueModel,
    SystemConfigModel,
)

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"
NOW = datetime(2026, 9, 25, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 and WS8_EVAL_DATABASE_URL for a dedicated eval DB",
)


def _frozen(name: str) -> dict[str, Any]:
    return json.loads((DATASET_ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def _evaluation_url() -> str:
    url = os.environ["WS8_EVAL_DATABASE_URL"]
    db_name = url.rsplit("/", maxsplit=1)[-1].split("?", maxsplit=1)[0]
    if "eval" not in db_name.lower():
        pytest.fail("WS8_EVAL_DATABASE_URL must name a dedicated evaluation database")
    if url == os.getenv("DATABASE_URL"):
        pytest.fail("WS8_EVAL_DATABASE_URL must not be the primary DATABASE_URL")
    return url


@pytest.fixture
async def prepared_postgres() -> Any:
    from project_agent.evaluation.fixtures import cleanup_v0, prepare_v0

    engine = create_async_engine(_evaluation_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    namespace = f"ws8-v0-postgres-red-{uuid4().hex}"
    dataset = load_evaluation_dataset(DATASET_ROOT)
    try:
        state = await prepare_v0(
            dataset=dataset,
            evaluation_namespace=namespace,
            session_factory=sessions,
            ragflow_adapter=None,
        )
        yield dataset, namespace, sessions, state
    finally:
        try:
            await cleanup_v0(
                evaluation_namespace=namespace,
                session_factory=sessions,
                ragflow_adapter=None,
            )
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_prepare_v0_materializes_projects_memberships_documents_and_issues(
    prepared_postgres: Any,
) -> None:
    dataset, namespace, sessions, state = prepared_postgres
    assert state["evaluation_namespace"] == namespace
    assert set(state["project_ids"]) == {"PRJ-RETAIL-ALPHA", "PRJ-LOGISTICS-BETA"}
    assert len(state["user_ids"]) == len(_frozen("identities.json")["identities"]) == 7
    for frozen in _frozen("identities.json")["identities"]:
        assert UUID(str(state["user_ids"][frozen["alias"]])) == UUID(frozen["user_id"])
    assert state["client_ids"]
    assert len(state["membership_ids"]) == len(_frozen("memberships.json")["memberships"]) == 6
    assert len(state["sandbox_issue_ids"]) == len(_frozen("sandbox-issues.json")["issues"]) == 7
    assert "company-public" not in state["project_ids"]  # Q046 stays unsupported.

    project_documents = {
        code: doc
        for code, doc in dataset.documents_by_code.items()
        if doc.project_code in state["project_ids"]
    }
    assert set(state["document_version_ids"]) == set(project_documents)
    assert len(project_documents) == 19  # 10 Alpha + 9 Beta; company-public is not a Run.

    async with sessions() as session:
        for code, project_id in state["project_ids"].items():
            project = await session.get(ProjectModel, UUID(str(project_id)))
            assert project is not None and project.code == code
            assert project.company_id == UUID(str(state["company_id"]))
            assert str(project.client_id) in {str(v) for v in state["client_ids"].values()}
            assert await session.scalar(
                select(func.count()).select_from(ProjectKnowledgeSpaceModel).where(
                    ProjectKnowledgeSpaceModel.project_id == project.id
                )
            ) == 1
        for frozen in _frozen("memberships.json")["memberships"]:
            membership = await session.get(
                ProjectMembershipModel,
                UUID(str(state["membership_ids"][frozen["fact_id"]])),
            )
            assert membership is not None
            assert membership.user_id == UUID(frozen["user_id"])
            assert membership.role == frozen["role"]
            assert membership.project_id == UUID(str(state["project_ids"][frozen["project_code"]]))
        for frozen in _frozen("sandbox-issues.json")["issues"]:
            issue = await session.get(
                SandboxIssueModel,
                UUID(str(state["sandbox_issue_ids"][frozen["issue_key"]])),
            )
            assert issue is not None and issue.issue_key == frozen["issue_key"]
            assert issue.title == frozen["title"]
            assert issue.status == frozen["status"]
            assert issue.project_id == UUID(str(state["project_ids"][frozen["project_code"]]))

        prompts = list(
            (
                await session.scalars(
                    select(SystemConfigModel).where(
                        SystemConfigModel.config_key == "prompt.qa.answer",
                        SystemConfigModel.enabled.is_(True),
                    )
                )
            ).all()
        )
        assert len(prompts) == 1
        assert isinstance(prompts[0].config_value_json.get("content"), str)
        assert prompts[0].config_value_json["content"]


@pytest.mark.asyncio
async def test_prepare_v0_is_idempotent(prepared_postgres: Any) -> None:
    from project_agent.evaluation.fixtures import prepare_v0

    dataset, namespace, sessions, first_state = prepared_postgres
    second_state = await prepare_v0(
        dataset=dataset,
        evaluation_namespace=namespace,
        session_factory=sessions,
        ragflow_adapter=None,
    )
    for key in (
        "company_id", "client_ids", "project_ids", "user_ids", "membership_ids",
        "document_ids", "document_version_ids", "knowledge_space_ids", "sandbox_issue_ids",
    ):
        assert first_state[key] == second_state[key], key

    async with sessions() as session:
        project_ids = [UUID(str(value)) for value in first_state["project_ids"].values()]
        assert await session.scalar(
            select(func.count()).select_from(ProjectModel).where(ProjectModel.id.in_(project_ids))
        ) == 2
        assert await session.scalar(
            select(func.count()).select_from(DocumentModel).where(
                DocumentModel.project_id.in_(project_ids)
            )
        ) == len(set(first_state["document_ids"].values()))
        assert await session.scalar(
            select(func.count()).select_from(SandboxIssueModel).where(
                SandboxIssueModel.project_id.in_(project_ids)
            )
        ) == 7


@pytest.mark.asyncio
async def test_prepare_v0_preserves_expired_and_outsider_membership_semantics(
    prepared_postgres: Any,
) -> None:
    _dataset, _namespace, sessions, state = prepared_postgres
    from project_agent.infrastructure.db.repositories.authorization import (
        SqlAlchemyProjectAuthorizationRepository,
    )

    frozen_memberships = _frozen("memberships.json")
    frozen_ids = _frozen("identities.json")["identities"]
    async with sessions() as session:
        auth = SqlAlchemyProjectAuthorizationRepository(session)
        for frozen in frozen_memberships["memberships"]:
            project_id = UUID(str(state["project_ids"][frozen["project_code"]]))
            actual = await auth.get_active_membership(
                user_id=UUID(frozen["user_id"]), project_id=project_id, at=NOW
            )
            assert (actual is not None) is frozen["expected_current"], frozen["fact_id"]
        outsider = next(item for item in frozen_ids if item["alias"] == "u-outsider")
        assert await auth.list_active_memberships_for_user(
            user_id=UUID(outsider["user_id"]), at=NOW
        ) == ()
        assert await session.scalar(
            select(func.count()).select_from(ProjectMembershipModel).where(
                ProjectMembershipModel.user_id == UUID(outsider["user_id"])
            )
        ) == 0


@pytest.mark.asyncio
async def test_prepare_v0_maps_every_project_doc_code_to_version_uuid(
    prepared_postgres: Any,
) -> None:
    dataset, _namespace, sessions, state = prepared_postgres
    assert state["integrity"]["corpus_sha256"] == dataset.integrity["corpus_sha256"]
    assert state["integrity"]["fixtures_sha256"] == dataset.integrity["fixtures_sha256"]
    project_docs = {
        code: doc for code, doc in dataset.documents_by_code.items()
        if doc.project_code in state["project_ids"]
    }
    async with sessions() as session:
        for code, frozen in project_docs.items():
            document = await session.get(DocumentModel, UUID(str(state["document_ids"][code])))
            version = await session.get(
                DocumentVersionModel, UUID(str(state["document_version_ids"][code]))
            )
            assert document is not None and version is not None, code
            assert document.project_id == UUID(str(state["project_ids"][frozen.project_code]))
            assert version.document_id == document.id
            assert version.version_label == frozen.version_label
            assert version.lifecycle_status == frozen.lifecycle_status
            assert version.content_hash == frozen.sha256
            if frozen.supersedes_doc_code:
                previous = frozen.supersedes_doc_code
                assert state["document_ids"][code] == state["document_ids"][previous]
                assert version.supersedes_version_id == UUID(
                    str(state["document_version_ids"][previous])
                )
                old = await session.get(
                    DocumentVersionModel, UUID(str(state["document_version_ids"][previous]))
                )
                assert old is not None and old.version_no < version.version_no


@pytest.mark.asyncio
async def test_prepare_v0_seeds_identifier_registry_from_frozen_identifiers(
    prepared_postgres: Any,
) -> None:
    dataset, _namespace, sessions, state = prepared_postgres
    async with sessions() as session:
        for code, frozen in dataset.documents_by_code.items():
            if frozen.project_code not in state["project_ids"]:
                continue
            for target in frozen.identifier_targets:
                matches = (
                    await session.execute(
                        select(DocumentIdentifierModel).where(
                            DocumentIdentifierModel.project_id == UUID(
                                str(state["project_ids"][frozen.project_code])
                            ),
                            DocumentIdentifierModel.document_version_id == UUID(
                                str(state["document_version_ids"][code])
                            ),
                            DocumentIdentifierModel.identifier_type == target["identifier_type"],
                            DocumentIdentifierModel.normalized_value == target["normalized_value"],
                        )
                    )
                ).scalars().all()
                assert len(matches) == 1, (code, target)
        # Identical identifier text in Alpha and Beta must not create cross-project rows.
        alpha_id = UUID(str(state["project_ids"]["PRJ-RETAIL-ALPHA"]))
        beta_id = UUID(str(state["project_ids"]["PRJ-LOGISTICS-BETA"]))
        assert alpha_id != beta_id


@pytest.mark.asyncio
async def test_cleanup_deletes_only_evaluation_owned_rows() -> None:
    from project_agent.evaluation.fixtures import cleanup_v0, prepare_v0

    engine = create_async_engine(_evaluation_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    namespace = f"ws8-v0-cleanup-red-{uuid4().hex}"
    unrelated_company_id = uuid4()
    unrelated_client_id = uuid4()
    unrelated_project_id = uuid4()
    unrelated_manager_id = uuid4()
    try:
        async with sessions() as session:
            session.add(ClientModel(
                id=unrelated_client_id,
                company_id=unrelated_company_id,
                name="WS8 cleanup sentinel — not evaluation-owned",
            ))
            await session.flush()
            session.add(ProjectModel(
                id=unrelated_project_id,
                company_id=unrelated_company_id,
                client_id=unrelated_client_id,
                code=f"NON-EVAL-{unrelated_project_id.hex[:8]}",
                name="Unrelated project cleanup sentinel",
                manager_id=unrelated_manager_id,
            ))
            await session.commit()
        state = await prepare_v0(
            dataset=load_evaluation_dataset(DATASET_ROOT),
            evaluation_namespace=namespace,
            session_factory=sessions,
            ragflow_adapter=None,
        )
        await cleanup_v0(
            evaluation_namespace=namespace, session_factory=sessions, ragflow_adapter=None
        )
        async with sessions() as session:
            assert await session.get(ClientModel, unrelated_client_id) is not None
            assert await session.get(ProjectModel, unrelated_project_id) is not None
            for project_id in state["project_ids"].values():
                assert await session.get(ProjectModel, UUID(str(project_id))) is None
            for issue_id in state["sandbox_issue_ids"].values():
                assert await session.get(SandboxIssueModel, UUID(str(issue_id))) is None
    finally:
        # Scoped to the exact sentinel PKs created here; no table-wide deletion.
        async with sessions() as session:
            await session.execute(
                ProjectModel.__table__.delete().where(ProjectModel.id == unrelated_project_id)
            )
            await session.execute(
                ClientModel.__table__.delete().where(ClientModel.id == unrelated_client_id)
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_prepare_v0_production_autoflush_false_persists_identifier_parents() -> None:
    """Live regression for the exact CLI session setting that previously raised FK errors."""
    from project_agent.evaluation.fixtures import cleanup_v0, prepare_v0
    from project_agent.infrastructure.db.session import create_session_factory

    engine = create_async_engine(_evaluation_url(), pool_pre_ping=True)
    sessions = create_session_factory(engine)  # production autoflush=False
    namespace = f"ws8-v0-autoflush-disabled-{uuid4().hex}"
    try:
        dataset = load_evaluation_dataset(DATASET_ROOT)
        state = await prepare_v0(
            dataset=dataset,
            evaluation_namespace=namespace,
            session_factory=sessions,
            ragflow_adapter=None,
        )
        async with sessions() as session:
            version_ids = [UUID(str(value)) for value in state["document_version_ids"].values()]
            assert await session.scalar(
                select(func.count()).select_from(DocumentVersionModel).where(
                    DocumentVersionModel.id.in_(version_ids)
                )
            ) == 19
            assert await session.scalar(
                select(func.count()).select_from(DocumentIdentifierModel).where(
                    DocumentIdentifierModel.document_version_id.in_(version_ids)
                )
            ) == 23
    finally:
        try:
            await cleanup_v0(
                evaluation_namespace=namespace,
                session_factory=sessions,
                ragflow_adapter=None,
            )
        finally:
            await engine.dispose()

@pytest.mark.asyncio
async def test_cleanup_deletes_runtime_citations_before_project_cascade() -> None:
    from project_agent.evaluation.fixtures import cleanup_v0, prepare_v0
    from project_agent.infrastructure.db.models.schema import (
        AgentRunModel,
        AnswerModel,
        CitationModel,
        EvidenceBundleModel,
        EvidenceSnapshotModel,
        ThreadModel,
    )

    engine = create_async_engine(_evaluation_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    namespace = f"ws8-v0-cleanup-citation-{uuid4().hex}"
    citation_id = uuid4()

    try:
        state = await prepare_v0(
            dataset=load_evaluation_dataset(DATASET_ROOT),
            evaluation_namespace=namespace,
            session_factory=sessions,
            ragflow_adapter=None,
        )

        project_id = UUID(
            str(state["project_ids"]["PRJ-RETAIL-ALPHA"])
        )
        company_id = UUID(str(state["company_id"]))
        user_id = UUID(str(state["user_ids"]["u-alpha-dev"]))

        thread_id = uuid4()
        run_id = uuid4()
        bundle_id = uuid4()
        snapshot_id = uuid4()
        answer_id = uuid4()

        async with sessions() as session:
            session.add(
                ThreadModel(
                    id=thread_id,
                    company_id=company_id,
                    project_id=project_id,
                    user_id=user_id,
                    title="WS8 cleanup citation regression",
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
                    business_mode="qa",
                    status="SUCCEEDED",
                )
            )
            await session.flush()

            session.add(
                EvidenceBundleModel(
                    id=bundle_id,
                    run_id=run_id,
                    query_text="WS8 cleanup citation regression",
                )
            )
            session.add(
                AnswerModel(
                    id=answer_id,
                    run_id=run_id,
                    answer_text="evaluation-owned answer",
                )
            )
            await session.flush()

            session.add(
                EvidenceSnapshotModel(
                    id=snapshot_id,
                    bundle_id=bundle_id,
                    project_id=project_id,
                    document_version_id=None,
                    source_type="document",
                    source_ref="cleanup-regression",
                    content="evaluation-owned evidence",
                    rank=1,
                )
            )
            await session.flush()

            session.add(
                CitationModel(
                    id=citation_id,
                    answer_id=answer_id,
                    evidence_snapshot_id=snapshot_id,
                    citation_no=1,
                )
            )
            await session.commit()

        await cleanup_v0(
            evaluation_namespace=namespace,
            session_factory=sessions,
            ragflow_adapter=None,
        )

        async with sessions() as session:
            assert await session.get(ProjectModel, project_id) is None
            assert await session.get(CitationModel, citation_id) is None
    finally:
        # RED cleanup safety: if the buggy cleanup failed, remove only the
        # exact citation created by this test, then retry namespace cleanup.
        async with sessions() as session:
            await session.execute(
                CitationModel.__table__.delete().where(
                    CitationModel.id == citation_id
                )
            )
            await session.commit()

        with contextlib.suppress(Exception):
            await cleanup_v0(
                evaluation_namespace=namespace,
                session_factory=sessions,
                ragflow_adapter=None,
            )

        await engine.dispose()
