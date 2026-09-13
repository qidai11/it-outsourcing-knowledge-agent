from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from project_agent.infrastructure.db.repositories.authorization import (
    SqlAlchemyProjectAuthorizationRepository,
)
from project_agent.infrastructure.db.models.schema import (
    ClientModel,
    DocumentModel,
    DocumentVersionModel,
    ProjectKnowledgeSpaceModel,
    ProjectMembershipModel,
    ProjectModel,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL authorization integration",
)


@pytest.mark.asyncio
async def test_repository_returns_only_active_membership_published_versions_and_spaces() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    company_id, client_id, project_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    published_id, draft_id = uuid4(), uuid4()

    async with sessions() as session:
        session.add(ClientModel(id=client_id, company_id=company_id, name="Auth Client"))
        session.add(
            ProjectModel(
                id=project_id,
                company_id=company_id,
                client_id=client_id,
                code=f"AUTH-{str(project_id)[:8]}",
                name="Auth Project",
                phase="test",
                manager_id=user_id,
            )
        )
        session.add(
            ProjectMembershipModel(
                project_id=project_id,
                user_id=user_id,
                role="developer",
                valid_from=now - timedelta(days=1),
                valid_to=None,
            )
        )
        doc = DocumentModel(
            company_id=company_id,
            project_id=project_id,
            document_category="requirement_baseline",
            title="Auth Requirements",
            owner_user_id=user_id,
        )
        session.add(doc)
        await session.flush()
        session.add_all(
            [
                DocumentVersionModel(
                    id=published_id,
                    document_id=doc.id,
                    version_no=1,
                    version_label="v1",
                    authority_level="requirement_baseline",
                    lifecycle_status="PUBLISHED",
                    created_by=user_id,
                ),
                DocumentVersionModel(
                    id=draft_id,
                    document_id=doc.id,
                    version_no=2,
                    version_label="v2-draft",
                    authority_level="requirement_baseline",
                    lifecycle_status="DRAFT",
                    created_by=user_id,
                ),
            ]
        )
        session.add_all(
            [
                ProjectKnowledgeSpaceModel(
                    project_id=project_id,
                    provider="ragflow",
                    external_space_id=f"ks-{project_id}",
                    status="active",
                ),
                ProjectKnowledgeSpaceModel(
                    project_id=project_id,
                    provider="other-provider",
                    external_space_id=f"other-{project_id}",
                    status="active",
                ),
            ]
        )
        await session.commit()

    async with sessions() as session:
        repo = SqlAlchemyProjectAuthorizationRepository(session)
        membership = await repo.get_active_membership(
            user_id=user_id, project_id=project_id, at=now
        )
        docs = await repo.list_published_document_access(project_id=project_id)
        spaces = await repo.list_active_knowledge_space_ids(project_id=project_id)

    assert membership is not None
    assert membership.project_id == project_id
    assert [item.document_version_id for item in docs] == [published_id]
    assert draft_id not in {item.document_version_id for item in docs}
    assert spaces == (f"ks-{project_id}",)

    async with sessions() as session:
        await session.execute(
            ProjectKnowledgeSpaceModel.__table__.delete().where(
                ProjectKnowledgeSpaceModel.project_id == project_id
            )
        )
        await session.execute(
            DocumentVersionModel.__table__.delete().where(
                DocumentVersionModel.document_id == doc.id
            )
        )
        await session.execute(DocumentModel.__table__.delete().where(DocumentModel.id == doc.id))
        await session.execute(
            ProjectMembershipModel.__table__.delete().where(
                ProjectMembershipModel.project_id == project_id
            )
        )
        await session.execute(ProjectModel.__table__.delete().where(ProjectModel.id == project_id))
        await session.execute(ClientModel.__table__.delete().where(ClientModel.id == client_id))
        await session.commit()
    await engine.dispose()
