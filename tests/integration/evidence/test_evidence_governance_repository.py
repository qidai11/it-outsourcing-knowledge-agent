from __future__ import annotations

import os
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from project_agent.infrastructure.db.models.schema import (
    ClientModel,
    DocumentModel,
    DocumentVersionModel,
    ProjectModel,
)
from project_agent.infrastructure.db.repositories.evidence_governance import (
    SqlAlchemyEvidenceGovernanceRepository,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run Evidence Governance PostgreSQL gate",
)


@pytest.mark.asyncio
async def test_repository_enriches_authority_and_marks_only_latest_published_version_current() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    company_id, client_id, project_id, manager_id = uuid4(), uuid4(), uuid4(), uuid4()
    old_id, current_id = uuid4(), uuid4()

    async with sessions() as session:
        session.add(ClientModel(id=client_id, company_id=company_id, name="Evidence Client"))
        session.add(ProjectModel(
            id=project_id,
            company_id=company_id,
            client_id=client_id,
            code=f"EVID-{str(project_id)[:8]}",
            name="Evidence Project",
            phase="test",
            manager_id=manager_id,
        ))
        doc = DocumentModel(
            company_id=company_id,
            project_id=project_id,
            document_category="requirement_baseline",
            title="Requirement Baseline",
            owner_user_id=manager_id,
        )
        session.add(doc)
        await session.flush()
        session.add_all([
            DocumentVersionModel(
                id=old_id,
                document_id=doc.id,
                version_no=1,
                version_label="v1",
                authority_level="requirement_baseline",
                lifecycle_status="PUBLISHED",
                effective_from=date(2026, 1, 1),
                created_by=manager_id,
            ),
            DocumentVersionModel(
                id=current_id,
                document_id=doc.id,
                version_no=2,
                version_label="v2",
                authority_level="approved_change",
                lifecycle_status="PUBLISHED",
                effective_from=date(2026, 7, 1),
                created_by=manager_id,
            ),
        ])
        await session.commit()
        doc_id = doc.id

    async with sessions() as session:
        repo = SqlAlchemyEvidenceGovernanceRepository(session)
        result = await repo.get_document_evidence_metadata(
            document_version_ids=(old_id, current_id)
        )

    assert result[old_id].is_current is False
    assert result[current_id].is_current is True
    assert result[current_id].authority_level.value == "approved_change"
    assert result[current_id].title == "Requirement Baseline"

    async with sessions() as session:
        await session.execute(DocumentVersionModel.__table__.delete().where(DocumentVersionModel.document_id == doc_id))
        await session.execute(DocumentModel.__table__.delete().where(DocumentModel.id == doc_id))
        await session.execute(ProjectModel.__table__.delete().where(ProjectModel.id == project_id))
        await session.execute(ClientModel.__table__.delete().where(ClientModel.id == client_id))
        await session.commit()
    await engine.dispose()
