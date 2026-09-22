from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from project_agent.application.services.authorization import (
    AuthorizationDenied,
    AuthorizationService,
)
from project_agent.observability.metrics import ObservabilityMetrics, metrics_context
from tests.fakes.authorization import FakeProjectAuthorizationRepository


@pytest.mark.asyncio
async def test_missing_membership_records_bounded_authorization_reason() -> None:
    service = AuthorizationService(
        FakeProjectAuthorizationRepository(),
        clock=lambda: datetime(2026, 9, 20, tzinfo=UTC),
    )
    metrics = ObservabilityMetrics()
    with metrics_context(metrics), pytest.raises(AuthorizationDenied):
        await service.authorize_project(user_id=uuid4(), project_id=uuid4())
    rendered = metrics.render_latest().decode()
    assert (
        'project_agent_authorization_denials_total'
        '{reason="no_active_membership"} 1.0' in rendered
    )
