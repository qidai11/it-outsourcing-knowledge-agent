from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from tests.fakes.authorization import FakeProjectAuthorizationRepository

from project_agent.application.services.authorization import (
    AuthorizationDenied,
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.domain.enums import ProjectRole

USER = UUID("11111111-1111-4111-8111-111111111111")
ALPHA = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BETA = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
CLIENT_A = UUID("aaaaaaaa-1111-4111-8111-111111111111")
CLIENT_B = UUID("bbbbbbbb-2222-4222-8222-222222222222")
COMPANY = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)


def _membership(project_id: UUID, client_id: UUID) -> MembershipAccessRecord:
    return MembershipAccessRecord(
        company_id=COMPANY,
        client_id=client_id,
        project_id=project_id,
        project_code=("PRJ-ALPHA" if project_id == ALPHA else "PRJ-BETA"),
        role=ProjectRole.DEVELOPER,
        valid_from=NOW - timedelta(days=10),
        valid_to=None,
    )


@pytest.mark.asyncio
async def test_alpha_member_cannot_build_beta_scope() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, ALPHA)] = _membership(ALPHA, CLIENT_A)
    service = AuthorizationService(repo, clock=lambda: NOW)

    with pytest.raises(AuthorizationDenied, match="membership"):
        await service.authorize_project(user_id=USER, project_id=BETA)


@pytest.mark.asyncio
async def test_scope_is_least_privilege_for_requested_project_only() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, ALPHA)] = _membership(ALPHA, CLIENT_A)
    repo.memberships[(USER, BETA)] = _membership(BETA, CLIENT_B)
    service = AuthorizationService(repo, clock=lambda: NOW)

    authorized = await service.authorize_project(user_id=USER, project_id=ALPHA)

    assert authorized.scope.allowed_project_ids == (ALPHA,)
    assert authorized.scope.allowed_client_ids == (CLIENT_A,)
    assert BETA not in authorized.scope.allowed_project_ids
    assert CLIENT_B not in authorized.scope.allowed_client_ids
