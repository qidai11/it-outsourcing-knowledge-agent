from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from project_agent.application.services.authorization import (
    AuthorizationDenied,
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.domain.enums import ProjectRole
from tests.fakes.authorization import FakeProjectAuthorizationRepository


USER = UUID("11111111-1111-4111-8111-111111111111")
PROJECT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
CLIENT = UUID("aaaaaaaa-1111-4111-8111-111111111111")
COMPANY = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_non_member_is_denied() -> None:
    service = AuthorizationService(FakeProjectAuthorizationRepository(), clock=lambda: NOW)

    with pytest.raises(AuthorizationDenied, match="membership"):
        await service.authorize_project(user_id=USER, project_id=PROJECT)


@pytest.mark.asyncio
async def test_expired_membership_is_denied() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = MembershipAccessRecord(
        company_id=COMPANY,
        client_id=CLIENT,
        project_id=PROJECT,
        project_code="PRJ-ALPHA",
        role=ProjectRole.DEVELOPER,
        valid_from=NOW - timedelta(days=30),
        valid_to=NOW - timedelta(seconds=1),
    )
    service = AuthorizationService(repo, clock=lambda: NOW)

    with pytest.raises(AuthorizationDenied, match="membership"):
        await service.authorize_project(user_id=USER, project_id=PROJECT)
