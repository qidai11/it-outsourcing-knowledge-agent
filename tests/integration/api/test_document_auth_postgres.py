from __future__ import annotations

import base64
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from tests.helpers.jwt import make_hs256_token

from project_agent.config import Settings
from project_agent.infrastructure.db.models.schema import (
    AuditLogModel,
    ClientModel,
    DocumentModel,
    DocumentVersionModel,
    ProjectMembershipModel,
    ProjectModel,
)
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL document auth integration",
)


@pytest.mark.asyncio
async def test_same_valid_jwt_is_rejected_after_postgres_membership_revocation(
    tmp_path: Path,
) -> None:
    database_url = os.environ["DATABASE_URL"]
    secret = "postgres-ws1-test-secret-value-123456"
    now = datetime.now(UTC)
    company_id = uuid4()
    client_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()

    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            session.add(
                ClientModel(
                    id=client_id,
                    company_id=company_id,
                    name=f"WS1 client {client_id}",
                    status="active",
                )
            )
            await session.flush()
            session.add(
                ProjectModel(
                    id=project_id,
                    company_id=company_id,
                    client_id=client_id,
                    code=f"WS1-{project_id.hex[:10]}",
                    name="WS1 auth project",
                    manager_id=user_id,
                    lifecycle_status="ACTIVE",
                )
            )
            await session.flush()
            session.add(
                ProjectMembershipModel(
                    project_id=project_id,
                    user_id=user_id,
                    role="developer",
                    valid_from=now - timedelta(minutes=5),
                    valid_to=None,
                )
            )
            await session.commit()

        settings = Settings(
            app_env="test",
            database_url=database_url,
            local_storage_root=tmp_path,
            ragflow_base_url="http://ragflow.invalid",
            ragflow_api_key=SecretStr("fake-ragflow-key"),
            ragflow_expected_version="fake-version",
            llm_base_url="http://llm.invalid",
            llm_api_key=SecretStr("fake-llm-key"),
            llm_model_alias="fake-model",
            llm_request_capacity=1,
            llm_token_capacity=1000,
            jwt_hs256_secret=SecretStr(secret),
            jwt_leeway_seconds=0,
        )
        token = make_hs256_token(
            user_id=user_id,
            secret=secret,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            expires_at=now + timedelta(hours=1),
            extra_claims={"role": "project_manager", "project_ids": [str(project_id)]},
        )
        payload = {
            "company_id": str(company_id),
            "project_id": str(project_id),
            "document_category": "approved_design",
            "title": "WS1 live document",
            "version_label": "v1",
            "authority_level": "approved_design",
            "filename": "ws1.md",
            "mime_type": "text/markdown",
            "content_base64": base64.b64encode(b"ws1").decode(),
            "owner_user_id": str(user_id),
        }
        headers = {"Authorization": f"Bearer {token}"}

        with TestClient(create_app(settings)) as client:
            first = client.post("/api/v1/documents", json=payload, headers=headers)
            assert first.status_code == 201
            assert first.json()["status"] == "DRAFT"

            async with sessions() as session:
                membership = (
                    await session.execute(
                        select(ProjectMembershipModel).where(
                            ProjectMembershipModel.project_id == project_id,
                            ProjectMembershipModel.user_id == user_id,
                        )
                    )
                ).scalar_one()
                membership.valid_to = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()

            second = client.post("/api/v1/documents", json=payload, headers=headers)
            assert second.status_code == 403

        async with sessions() as session:
            version_count = await session.scalar(
                select(func.count(DocumentVersionModel.id))
                .join(DocumentModel, DocumentModel.id == DocumentVersionModel.document_id)
                .where(DocumentModel.project_id == project_id)
            )
            audit_count = await session.scalar(
                select(func.count(AuditLogModel.id)).where(
                    AuditLogModel.project_id == project_id,
                    AuditLogModel.action == "document_metadata_confirmed",
                )
            )
            created_by = await session.scalar(
                select(DocumentVersionModel.created_by)
                .join(DocumentModel, DocumentModel.id == DocumentVersionModel.document_id)
                .where(DocumentModel.project_id == project_id)
            )
            assert version_count == 1
            assert audit_count == 1
            assert created_by == user_id
    finally:
        async with sessions() as session:
            await session.execute(
                delete(AuditLogModel).where(AuditLogModel.project_id == project_id)
            )
            await session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
            await session.execute(delete(ClientModel).where(ClientModel.id == client_id))
            await session.commit()
        await engine.dispose()
