from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.application.services.identifier_registry import IdentifierRegistryService
from project_agent.domain.identifiers import IdentifierType, ManualIdentifier
from project_agent.infrastructure.db.models.schema import (
    ClientModel,
    DocumentModel,
    DocumentVersionModel,
    ProjectModel,
)
from project_agent.infrastructure.db.repositories.identifiers import (
    SqlAlchemyIdentifierRegistryRepository,
)

RUN_POSTGRES_INTEGRATION = os.getenv("RUN_POSTGRES_INTEGRATION") == "1"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_POSTGRES_INTEGRATION,
    reason="set RUN_POSTGRES_INTEGRATION=1 after applying migrations",
)
async def test_postgres_registry_exact_lookup_and_trigram_suggestion() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    company_id = uuid4()
    manager_id = uuid4()
    owner_id = uuid4()
    client = ClientModel(id=uuid4(), company_id=company_id, name="Identifier Test Client")
    alpha = ProjectModel(
        id=uuid4(),
        company_id=company_id,
        client_id=client.id,
        code=f"PRJ-ALPHA-{uuid4().hex[:6].upper()}",
        name="Alpha",
        manager_id=manager_id,
    )
    beta = ProjectModel(
        id=uuid4(),
        company_id=company_id,
        client_id=client.id,
        code=f"PRJ-BETA-{uuid4().hex[:6].upper()}",
        name="Beta",
        manager_id=manager_id,
    )

    async with session_factory() as session:
        try:
            session.add(client)
            await session.flush()
            session.add_all([alpha, beta])
            await session.flush()

            alpha_doc = DocumentModel(
                id=uuid4(), company_id=company_id, project_id=alpha.id,
                document_category="requirement_baseline", title="Alpha Req", owner_user_id=owner_id,
            )
            beta_doc = DocumentModel(
                id=uuid4(), company_id=company_id, project_id=beta.id,
                document_category="requirement_baseline", title="Beta Req", owner_user_id=owner_id,
            )
            session.add_all([alpha_doc, beta_doc])
            await session.flush()

            alpha_version = DocumentVersionModel(
                id=uuid4(), document_id=alpha_doc.id, version_no=1, version_label="v1",
                authority_level="requirement_baseline", lifecycle_status="PUBLISHED",
                source_uri="local://alpha", content_hash="alpha", created_by=owner_id,
            )
            beta_version = DocumentVersionModel(
                id=uuid4(), document_id=beta_doc.id, version_no=1, version_label="v1",
                authority_level="requirement_baseline", lifecycle_status="PUBLISHED",
                source_uri="local://beta", content_hash="beta", created_by=owner_id,
            )
            session.add_all([alpha_version, beta_version])
            await session.flush()

            repository = SqlAlchemyIdentifierRegistryRepository(session)
            service = IdentifierRegistryService(repository, IdentifierExtractor())
            await service.index_text(
                company_id=company_id,
                project_id=alpha.id,
                document_version_id=alpha_version.id,
                text="REQ-3.2.1 /api/v1/import t_order_detail",
            )
            await service.index_text(
                company_id=company_id,
                project_id=beta.id,
                document_version_id=beta_version.id,
                text="REQ-3.2.1 /api/v1/import t_order_detail",
            )

            alpha_hits = await service.find_exact(
                project_id=alpha.id,
                identifier_type=IdentifierType.REQUIREMENT_ID,
                value="req-3.2.1",
            )
            assert len(alpha_hits) == 1
            assert alpha_hits[0].project_id == alpha.id
            assert alpha_hits[0].document_version_id == alpha_version.id

            suggestions = await service.suggest_spelling(
                project_id=alpha.id,
                identifier_type=IdentifierType.REQUIREMENT_ID,
                value="REQ-3.2.l",
                threshold=0.2,
            )
            assert any(s.normalized_value == "REQ-3.2.1" for s in suggestions)

            await service.index_text(
                company_id=company_id,
                project_id=alpha.id,
                document_version_id=alpha_version.id,
                text="REQ-3.2.1",
                manual_identifiers=(
                    ManualIdentifier(
                        identifier_type=IdentifierType.REQUIREMENT_ID,
                        raw_value="REQ-8.8.8",
                    ),
                ),
            )
            assert await service.find_exact(
                project_id=alpha.id,
                identifier_type=IdentifierType.REQUIREMENT_ID,
                value="REQ-3.2.1",
            ) == ()
            assert len(
                await service.find_exact(
                    project_id=alpha.id,
                    identifier_type=IdentifierType.REQUIREMENT_ID,
                    value="REQ-8.8.8",
                )
            ) == 1

            async with engine.connect() as connection:
                def index_names(sync_connection: object) -> set[str]:
                    indexes = inspect(sync_connection).get_indexes("document_identifiers")
                    return {index["name"] for index in indexes}

                names = await connection.run_sync(index_names)
                assert "idx_identifier_exact" in names
                assert "idx_identifier_trgm" in names

                plan = (
                    await connection.execute(
                        text(
                            "EXPLAIN SELECT * FROM document_identifiers "
                            "WHERE project_id = :project_id "
                            "AND identifier_type = 'requirement_id' "
                            "AND normalized_value = 'REQ-8.8.8'"
                        ),
                        {"project_id": alpha.id},
                    )
                ).scalars().all()
                assert all("vector" not in line.lower() for line in plan)

            await session.rollback()
        finally:
            await session.rollback()
            await engine.dispose()
