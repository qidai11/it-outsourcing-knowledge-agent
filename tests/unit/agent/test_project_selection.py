from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.fakes.authorization import FakeProjectAuthorizationRepository

from project_agent.agent.nodes.analyze_query import QueryAnalysisService
from project_agent.agent.nodes.select_project import ProjectSelectionService
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationService,
    MembershipAccessRecord,
)
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.domain.enums import ProjectRole


@pytest.mark.asyncio
async def test_multiple_memberships_without_project_requires_clarification() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    user_id = uuid4()
    company_id = uuid4()
    repo = FakeProjectAuthorizationRepository()
    for code in ("PRJ-A", "PRJ-B"):
        project_id = uuid4()
        repo.memberships[(user_id, project_id)] = MembershipAccessRecord(
            company_id=company_id,
            client_id=uuid4(),
            project_id=project_id,
            project_code=code,
            role=ProjectRole.DEVELOPER,
            valid_from=now - timedelta(days=1),
            valid_to=None,
        )
    selector = ProjectSelectionService(AuthorizationService(repo, clock=lambda: now))
    analysis = QueryAnalysisService(IdentifierExtractor()).analyze("登录失败多少次锁定？")

    result = await selector.select(
        identity=AuthenticatedIdentity(user_id=user_id),
        analysis=analysis,
        requested_project_id=None,
    )

    assert result.route == "clarification"
    assert result.error_code == "PROJECT_REQUIRED"
    assert result.selected_project_id is None


@pytest.mark.asyncio
async def test_query_project_code_selects_only_authorized_project() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    user_id = uuid4()
    project_id = uuid4()
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(user_id, project_id)] = MembershipAccessRecord(
        company_id=uuid4(),
        client_id=uuid4(),
        project_id=project_id,
        project_code="PRJ-ALPHA",
        role=ProjectRole.DEVELOPER,
        valid_from=now - timedelta(days=1),
        valid_to=None,
    )
    selector = ProjectSelectionService(AuthorizationService(repo, clock=lambda: now))
    analysis = QueryAnalysisService(IdentifierExtractor()).analyze("PRJ-BETA-DEMO 的接口是什么？")

    result = await selector.select(
        identity=AuthenticatedIdentity(user_id=user_id),
        analysis=analysis,
        requested_project_id=None,
    )

    assert result.route == "refusal"
    assert result.error_code == "PROJECT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_explicit_project_id_conflicting_with_query_project_code_is_not_silently_accepted(
) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    user_id = uuid4()
    alpha_id = uuid4()
    beta_id = uuid4()
    repo = FakeProjectAuthorizationRepository()
    for project_id, code in ((alpha_id, "PRJ-ALPHA-DEMO"), (beta_id, "PRJ-BETA-DEMO")):
        repo.memberships[(user_id, project_id)] = MembershipAccessRecord(
            company_id=uuid4(),
            client_id=uuid4(),
            project_id=project_id,
            project_code=code,
            role=ProjectRole.DEVELOPER,
            valid_from=now - timedelta(days=1),
            valid_to=None,
        )
    selector = ProjectSelectionService(AuthorizationService(repo, clock=lambda: now))
    analysis = QueryAnalysisService(IdentifierExtractor()).analyze(
        "PRJ-BETA-DEMO 的 REQ-3.2.1 是什么？"
    )

    result = await selector.select(
        identity=AuthenticatedIdentity(user_id=user_id),
        analysis=analysis,
        requested_project_id=alpha_id,
    )

    assert result.route == "clarification"
    assert result.error_code == "PROJECT_MISMATCH"
    assert result.selected_project_id is None
