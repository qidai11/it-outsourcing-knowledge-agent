from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from project_agent.domain.enums import ProjectDeliveryMode, ProjectLifecycleStatus, ProjectRole
from project_agent.domain.projects import Project, ProjectMembership


def test_membership_is_active_inside_validity_window() -> None:
    now = datetime(2026, 8, 8, 7, 30, tzinfo=UTC)
    membership = ProjectMembership(
        project_id=uuid4(),
        user_id=uuid4(),
        role=ProjectRole.DEVELOPER,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=1),
    )

    assert membership.is_active_at(now)


def test_membership_is_inactive_at_valid_to_boundary() -> None:
    now = datetime(2026, 8, 8, 7, 30, tzinfo=UTC)
    membership = ProjectMembership(
        project_id=uuid4(),
        user_id=uuid4(),
        role=ProjectRole.QA,
        valid_from=now - timedelta(days=1),
        valid_to=now,
    )

    assert not membership.is_active_at(now)


def test_membership_without_valid_to_remains_active() -> None:
    now = datetime(2026, 8, 8, 7, 30, tzinfo=UTC)
    membership = ProjectMembership(
        project_id=uuid4(),
        user_id=uuid4(),
        role=ProjectRole.SUPPORT,
        valid_from=now - timedelta(days=1),
        valid_to=None,
    )

    assert membership.is_active_at(now)


def test_v1_project_defaults_are_internal_and_active() -> None:
    project = Project(
        id=uuid4(),
        company_id=uuid4(),
        client_id=uuid4(),
        code="PRJ-RETAIL-ALPHA",
        name="订单与库存协同平台升级项目",
        phase="UAT",
        manager_id=uuid4(),
    )

    assert project.delivery_mode is ProjectDeliveryMode.INTERNAL_ONLY
    assert project.lifecycle_status is ProjectLifecycleStatus.ACTIVE
