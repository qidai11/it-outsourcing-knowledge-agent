from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.document_repository import InMemoryDocumentWorkflowRepository
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.object_store import InMemoryObjectStore
from tests.helpers.jwt import make_hs256_token

from project_agent.api.v1.documents import (
    DocumentApiServices,
    get_document_access_service,
    get_document_api_services,
)
from project_agent.application.services.authorization import (
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.application.services.document_access import DocumentAccessService
from project_agent.application.use_cases.delete_document import DeleteDocumentUseCase
from project_agent.application.use_cases.publish_document import PublishDocumentUseCase
from project_agent.application.use_cases.review_document import (
    ApproveDocumentUseCase,
    SubmitDocumentReviewUseCase,
)
from project_agent.application.use_cases.upload_document import UploadDocumentUseCase
from project_agent.config import Settings
from project_agent.domain.enums import DocumentLifecycleStatus, ProjectRole
from project_agent.infrastructure.auth.jwt import JwtIdentityVerifier
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.main import create_app
from project_agent.runtime.api import ApiRuntime

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
SECRET = "s" * 32
USER = UUID("11111111-1111-4111-8111-111111111111")
COMPANY = UUID("22222222-2222-4222-8222-222222222222")
OTHER_COMPANY = UUID("33333333-3333-4333-8333-333333333333")
CLIENT = UUID("44444444-4444-4444-8444-444444444444")
PROJECT_ALPHA = UUID("55555555-5555-4555-8555-555555555555")
PROJECT_BETA = UUID("66666666-6666-4666-8666-666666666666")


def _membership(role: ProjectRole, *, project_id: UUID = PROJECT_ALPHA) -> MembershipAccessRecord:
    return MembershipAccessRecord(
        company_id=COMPANY,
        client_id=CLIENT,
        project_id=project_id,
        project_code="PRJ-ALPHA" if project_id == PROJECT_ALPHA else "PRJ-BETA",
        role=role,
        valid_from=NOW - timedelta(days=1),
        valid_to=None,
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=(
            "postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent"
        ),
        local_storage_root=tmp_path,
        ragflow_base_url="http://ragflow.invalid",
        ragflow_api_key=SecretStr("fake-ragflow-key"),
        ragflow_expected_version="fake-version",
        llm_base_url="http://llm.invalid",
        llm_api_key=SecretStr("fake-llm-key"),
        llm_model_alias="fake-model",
        llm_request_capacity=1,
        llm_token_capacity=1000,
        jwt_hs256_secret=SecretStr(SECRET),
        jwt_leeway_seconds=0,
    )


class ApiHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.settings = _settings(tmp_path)
        self.auth_repo = FakeProjectAuthorizationRepository()
        self.documents = InMemoryDocumentWorkflowRepository()
        self.documents.bind_project_code(PROJECT_ALPHA, "PRJ-ALPHA")
        self.documents.bind_project_code(PROJECT_BETA, "PRJ-BETA")
        self.object_store = InMemoryObjectStore()
        self.knowledge = FakeKnowledgePort()
        self.access = DocumentAccessService(
            authorization=AuthorizationService(self.auth_repo, clock=lambda: NOW),
            repository=self.documents,
        )
        self.services = DocumentApiServices(
            upload=UploadDocumentUseCase(self.documents, self.object_store),
            submit_review=SubmitDocumentReviewUseCase(self.documents),
            approve=ApproveDocumentUseCase(self.documents),
            publish=PublishDocumentUseCase(self.documents, self.knowledge),
            delete=DeleteDocumentUseCase(self.documents, self.knowledge),
        )

        @asynccontextmanager
        async def fake_runtime_factory(resolved: Settings) -> AsyncIterator[ApiRuntime]:
            engine = create_engine(resolved.database_url)
            try:
                yield ApiRuntime(
                    settings=resolved,
                    engine=engine,
                    session_factory=create_session_factory(engine),
                    object_store=self.object_store,
                    knowledge=self.knowledge,
                    jwt_verifier=JwtIdentityVerifier(
                        secret=SECRET,
                        issuer=resolved.jwt_issuer,
                        audience=resolved.jwt_audience,
                        leeway_seconds=0,
                        clock=lambda: NOW,
                    ),
                )
            finally:
                await engine.dispose()

        self.app = create_app(self.settings, runtime_factory=fake_runtime_factory)
        self.app.dependency_overrides[get_document_api_services] = lambda: self.services
        self.app.dependency_overrides[get_document_access_service] = lambda: self.access

    def token(self, *, user_id: UUID = USER, **claims: object) -> str:
        return make_hs256_token(
            user_id=user_id,
            secret=SECRET,
            issuer=self.settings.jwt_issuer,
            audience=self.settings.jwt_audience,
            expires_at=NOW + timedelta(minutes=30),
            extra_claims=claims or None,
        )

    def headers(self, **claims: object) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(**claims)}"}

    def upload_payload(
        self,
        *,
        project_id: UUID = PROJECT_ALPHA,
        company_id: UUID = COMPANY,
    ) -> dict[str, object]:
        return {
            "company_id": str(company_id),
            "project_id": str(project_id),
            "document_category": "approved_design",
            "title": "Design",
            "version_label": "v1.0",
            "authority_level": "approved_design",
            "filename": "design.md",
            "mime_type": "text/markdown",
            "content_base64": base64.b64encode(b"design").decode(),
            "owner_user_id": str(USER),
        }

    @property
    def version_count(self) -> int:
        return len(self.documents._versions)  # noqa: SLF001 - intentional test fake inspection


def test_missing_jwt_rejects_upload_without_creating_draft(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)

    with TestClient(h.app) as client:
        response = client.post("/api/v1/documents", json=h.upload_payload())

    assert response.status_code == 401
    assert h.version_count == 0


def test_forged_project_manager_claim_does_not_override_viewer_membership(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT_ALPHA)] = _membership(ProjectRole.VIEWER)

    with TestClient(h.app) as client:
        response = client.post(
            "/api/v1/documents",
            json=h.upload_payload(),
            headers=h.headers(role="project_manager", project_ids=[str(PROJECT_ALPHA)]),
        )

    assert response.status_code == 403
    assert h.version_count == 0


def test_current_developer_membership_uploads_draft_as_jwt_subject(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT_ALPHA)] = _membership(ProjectRole.DEVELOPER)

    with TestClient(h.app) as client:
        response = client.post(
            "/api/v1/documents",
            json=h.upload_payload(),
            headers=h.headers(),
        )

    assert response.status_code == 201
    version_id = UUID(response.json()["version_id"])
    assert response.json()["status"] == "DRAFT"
    assert h.documents.get_now(version_id).created_by == USER


def test_alpha_membership_cannot_upload_to_beta(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT_ALPHA)] = _membership(ProjectRole.DEVELOPER)

    with TestClient(h.app) as client:
        response = client.post(
            "/api/v1/documents",
            json=h.upload_payload(project_id=PROJECT_BETA),
            headers=h.headers(),
        )

    assert response.status_code == 403
    assert h.version_count == 0


def test_upload_company_must_match_current_membership(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT_ALPHA)] = _membership(ProjectRole.DEVELOPER)

    with TestClient(h.app) as client:
        response = client.post(
            "/api/v1/documents",
            json=h.upload_payload(company_id=OTHER_COMPANY),
            headers=h.headers(),
        )

    assert response.status_code == 403
    assert h.version_count == 0


def test_same_valid_jwt_is_denied_immediately_after_membership_expiry(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT_ALPHA)] = _membership(ProjectRole.DEVELOPER)
    headers = h.headers()

    with TestClient(h.app) as client:
        first = client.post("/api/v1/documents", json=h.upload_payload(), headers=headers)
        h.auth_repo.memberships[(USER, PROJECT_ALPHA)] = replace(
            _membership(ProjectRole.DEVELOPER), valid_to=NOW
        )
        second = client.post("/api/v1/documents", json=h.upload_payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 403
    assert h.version_count == 1


def test_developer_cannot_publish_and_does_not_ingest(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT_ALPHA)] = _membership(ProjectRole.DEVELOPER)
    version = h.documents.seed_version(
        company_id=COMPANY,
        project_id=PROJECT_ALPHA,
        document_category="approved_design",
        title="Design",
        version_label="v1.0",
        authority_level="approved_design",
        lifecycle_status=DocumentLifecycleStatus.APPROVED,
        owner_user_id=USER,
    )
    h.documents.bind_knowledge_space(PROJECT_ALPHA, "ks-alpha")

    with TestClient(h.app) as client:
        response = client.post(
            f"/api/v1/documents/{version.version_id}/publish",
            headers=h.headers(),
        )

    assert response.status_code == 403
    assert h.knowledge.ingested_requests == []


def test_project_manager_can_publish_existing_approved_version(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)
    h.auth_repo.memberships[(USER, PROJECT_ALPHA)] = _membership(ProjectRole.PROJECT_MANAGER)
    version = h.documents.seed_version(
        company_id=COMPANY,
        project_id=PROJECT_ALPHA,
        document_category="approved_design",
        title="Design",
        version_label="v1.0",
        authority_level="approved_design",
        lifecycle_status=DocumentLifecycleStatus.APPROVED,
        owner_user_id=USER,
    )
    h.documents.bind_knowledge_space(PROJECT_ALPHA, "ks-alpha")

    with TestClient(h.app) as client:
        response = client.post(
            f"/api/v1/documents/{version.version_id}/publish",
            headers=h.headers(),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "PUBLISHED"
    assert len(h.knowledge.ingested_requests) == 1


def test_unknown_version_is_404_but_known_version_without_membership_is_403(tmp_path: Path) -> None:
    h = ApiHarness(tmp_path)
    known = h.documents.seed_version(
        company_id=COMPANY,
        project_id=PROJECT_ALPHA,
        document_category="approved_design",
        title="Design",
        version_label="v1.0",
        authority_level="approved_design",
        lifecycle_status=DocumentLifecycleStatus.APPROVED,
        owner_user_id=USER,
    )

    with TestClient(h.app) as client:
        unknown_response = client.post(
            f"/api/v1/documents/{UUID('77777777-7777-4777-8777-777777777777')}/publish",
            headers=h.headers(),
        )
        known_response = client.post(
            f"/api/v1/documents/{known.version_id}/publish",
            headers=h.headers(),
        )

    assert unknown_response.status_code == 404
    assert known_response.status_code == 403
