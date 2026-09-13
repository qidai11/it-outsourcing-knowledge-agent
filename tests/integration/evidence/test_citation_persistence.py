from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.evidence import CitationReference, GovernedEvidence, GovernedEvidencePack
from project_agent.infrastructure.db.models.schema import (
    AgentRunModel,
    CitationModel,
    ClientModel,
    DocumentModel,
    DocumentVersionModel,
    ProjectModel,
    ThreadModel,
)
from project_agent.infrastructure.db.repositories.qa_graph import SqlAlchemyQAGraphStore

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run Citation persistence PostgreSQL gate",
)


@pytest.mark.asyncio
async def test_governed_snapshot_and_citation_reference_are_persisted() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    company_id, client_id, project_id, user_id, thread_id, run_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    version_id = uuid4()

    async with sessions() as session:
        session.add(ClientModel(id=client_id, company_id=company_id, name="Citation Client"))
        session.add(ProjectModel(
            id=project_id,
            company_id=company_id,
            client_id=client_id,
            code=f"CITE-{str(project_id)[:8]}",
            name="Citation Project",
            phase="test",
            manager_id=user_id,
        ))
        doc = DocumentModel(
            company_id=company_id,
            project_id=project_id,
            document_category="requirement_baseline",
            title="Citation Requirement",
            owner_user_id=user_id,
        )
        session.add(doc)
        await session.flush()
        session.add(DocumentVersionModel(
            id=version_id,
            document_id=doc.id,
            version_no=1,
            version_label="v1",
            authority_level="requirement_baseline",
            lifecycle_status="PUBLISHED",
            created_by=user_id,
        ))
        session.add(ThreadModel(
            id=thread_id,
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
        ))
        session.add(AgentRunModel(
            id=run_id,
            thread_id=thread_id,
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
        ))
        await session.flush()
        store = SqlAlchemyQAGraphStore(session)
        bundle_id = await store.save_governed_evidence_bundle(
            run_id=run_id,
            project_id=project_id,
            query_text="REQ-3.2.1?",
            pack=GovernedEvidencePack(
                evidence=(GovernedEvidence(
                    label="E1",
                    project_id=project_id,
                    project_code="PRJ-RETAIL-ALPHA",
                    document_version_id=version_id,
                    document_category=DocumentCategory.REQUIREMENT_BASELINE,
                    document_title="Citation Requirement",
                    version_no=1,
                    version_label="v1",
                    authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
                    lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
                    is_current=True,
                    effective_from=None,
                    effective_to=None,
                    content="锁定 30 分钟",
                    score=0.9,
                    knowledge_space_id="dataset-alpha",
                    provider_ref="chunk-1",
                    page_no=1,
                    section="3.2.1",
                    provider_metadata={},
                    conflict_key=None,
                    claim_value=None,
                    unresolved_conflict=False,
                ),),
                unresolved_conflicts={},
            ),
        )
        frozen = await store.load_governed_evidence_bundle(bundle_id)
        answer_id = await store.save_grounded_answer(
            run_id=run_id,
            answer_text="锁定 30 分钟。 [E1]",
            citations=(
                CitationReference(
                    citation_no=1,
                    evidence_snapshot_id=frozen.evidence[0].snapshot_id,
                ),
            ),
        )
        await session.commit()
        citation = (
            await session.scalars(
                select(CitationModel).where(CitationModel.answer_id == answer_id)
            )
        ).one()
        assert citation.evidence_snapshot_id == frozen.evidence[0].snapshot_id
        doc_id = doc.id

        # Snapshot is a historical fact: source version deletion must not erase
        # the frozen version identifier needed to audit an already-saved answer.
        await session.execute(
            DocumentVersionModel.__table__.delete().where(DocumentVersionModel.id == version_id)
        )
        await session.flush()
        reloaded = await store.load_governed_evidence_bundle(bundle_id)
        assert reloaded.evidence[0].document_version_id == version_id

    async with sessions() as session:
        await session.execute(
            CitationModel.__table__.delete().where(CitationModel.answer_id == answer_id)
        )
        # Answer/evidence/event rows cascade from run where applicable.
        await session.execute(AgentRunModel.__table__.delete().where(AgentRunModel.id == run_id))
        await session.execute(ThreadModel.__table__.delete().where(ThreadModel.id == thread_id))
        await session.execute(DocumentModel.__table__.delete().where(DocumentModel.id == doc_id))
        await session.execute(ProjectModel.__table__.delete().where(ProjectModel.id == project_id))
        await session.execute(ClientModel.__table__.delete().where(ClientModel.id == client_id))
        await session.commit()
    await engine.dispose()
