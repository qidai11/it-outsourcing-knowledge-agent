from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationDenied,
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.application.services.document_access import (
    DocumentAccessService,
    DocumentOperation,
)
from project_agent.domain.enums import DocumentLifecycleStatus, ProjectRole
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.document_repository import InMemoryDocumentWorkflowRepository

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
USER = UUID("11111111-1111-4111-8111-111111111111")
COMPANY = UUID("22222222-2222-4222-8222-222222222222")
OTHER_COMPANY = UUID("33333333-3333-4333-8333-333333333333")
CLIENT = UUID("44444444-4444-4444-8444-444444444444")
PROJECT = UUID("55555555-5555-4555-8555-555555555555")
OTHER_PROJECT = UUID("66666666-6666-4666-8666-666666666666")


def membership(role: ProjectRole, *, project_id: UUID = PROJECT) -> MembershipAccessRecord:
    return MembershipAccessRecord(
        company_id=COMPANY,
        client_id=CLIENT,
        project_id=project_id,
        project_code="PRJ-ALPHA" if project_id == PROJECT else "PRJ-BETA",
        role=role,
        valid_from=NOW - timedelta(days=1),
        valid_to=None,
    )


def service_for(
    auth_repo: FakeProjectAuthorizationRepository,
    document_repo: InMemoryDocumentWorkflowRepository | None = None,
) -> DocumentAccessService:
    return DocumentAccessService(
        authorization=AuthorizationService(auth_repo, clock=lambda: NOW),
        repository=document_repo or InMemoryDocumentWorkflowRepository(),
    )


@pytest.mark.asyncio
async def test_developer_gets_only_member_document_write_permissions() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.DEVELOPER)

    allowed = await service_for(repo).authorize_project_operation(
        identity=AuthenticatedIdentity(user_id=USER),
        project_id=PROJECT,
        operation=DocumentOperation.UPLOAD,
        expected_company_id=COMPANY,
    )

    assert allowed.actor.user_id == USER
    assert allowed.actor.permissions == frozenset({"upload_document", "submit_review"})


@pytest.mark.asyncio
async def test_viewer_cannot_upload_even_if_identity_is_authenticated() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.VIEWER)

    with pytest.raises(AuthorizationDenied, match="upload_document"):
        await service_for(repo).authorize_project_operation(
            identity=AuthenticatedIdentity(user_id=USER),
            project_id=PROJECT,
            operation=DocumentOperation.UPLOAD,
            expected_company_id=COMPANY,
        )


@pytest.mark.asyncio
async def test_project_manager_has_publish_approve_and_archive_permissions() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.PROJECT_MANAGER)

    allowed = await service_for(repo).authorize_project_operation(
        identity=AuthenticatedIdentity(user_id=USER),
        project_id=PROJECT,
        operation=DocumentOperation.PUBLISH,
        expected_company_id=COMPANY,
    )

    assert {"approve_document", "publish_document", "archive_document"} <= (
        allowed.actor.permissions
    )


@pytest.mark.asyncio
async def test_developer_cannot_approve_document() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.DEVELOPER)

    with pytest.raises(AuthorizationDenied, match="approve_document"):
        await service_for(repo).authorize_project_operation(
            identity=AuthenticatedIdentity(user_id=USER),
            project_id=PROJECT,
            operation=DocumentOperation.APPROVE,
        )


@pytest.mark.asyncio
async def test_payload_company_must_match_membership_company() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.DEVELOPER)

    with pytest.raises(AuthorizationDenied, match="company"):
        await service_for(repo).authorize_project_operation(
            identity=AuthenticatedIdentity(user_id=USER),
            project_id=PROJECT,
            operation=DocumentOperation.UPLOAD,
            expected_company_id=OTHER_COMPANY,
        )


@pytest.mark.asyncio
async def test_no_active_membership_is_denied() -> None:
    repo = FakeProjectAuthorizationRepository()

    with pytest.raises(AuthorizationDenied, match="active project membership"):
        await service_for(repo).authorize_project_operation(
            identity=AuthenticatedIdentity(user_id=USER),
            project_id=PROJECT,
            operation=DocumentOperation.UPLOAD,
        )


@pytest.mark.asyncio
async def test_same_identity_is_denied_after_membership_expires() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = membership(ProjectRole.DEVELOPER)
    service = service_for(repo)
    identity = AuthenticatedIdentity(user_id=USER)

    await service.authorize_project_operation(
        identity=identity,
        project_id=PROJECT,
        operation=DocumentOperation.UPLOAD,
    )
    repo.memberships[(USER, PROJECT)] = replace(
        membership(ProjectRole.DEVELOPER), valid_to=NOW
    )

    with pytest.raises(AuthorizationDenied, match="active project membership"):
        await service.authorize_project_operation(
            identity=identity,
            project_id=PROJECT,
            operation=DocumentOperation.UPLOAD,
        )


@pytest.mark.asyncio
async def test_version_authorization_uses_versions_true_project_and_company() -> None:
    auth_repo = FakeProjectAuthorizationRepository()
    auth_repo.memberships[(USER, PROJECT)] = membership(ProjectRole.PROJECT_MANAGER)
    document_repo = InMemoryDocumentWorkflowRepository()
    version = document_repo.seed_version(
        company_id=OTHER_COMPANY,
        project_id=OTHER_PROJECT,
        document_category="approved_design",
        title="Beta design",
        version_label="v1",
        authority_level="approved_design",
        lifecycle_status=DocumentLifecycleStatus.APPROVED,
        owner_user_id=USER,
    )

    with pytest.raises(AuthorizationDenied, match="active project membership"):
        await service_for(auth_repo, document_repo).authorize_version_operation(
            identity=AuthenticatedIdentity(user_id=USER),
            version_id=version.version_id,
            operation=DocumentOperation.PUBLISH,
        )
