from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.fakes.issue_workflow import FakeIssueWorkflowRepository

from project_agent.application.services.issue_confirmation import (
    ConfirmationPayloadMismatch,
    IssueConfirmationService,
)
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.issues import (
    ConfirmationAction,
    IssueDraftCreate,
    ToolConfirmationStatus,
)


@pytest.mark.asyncio
async def test_confirmation_binds_exact_payload_hash() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    draft = await drafts.create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=uuid4(), text="ERR-IMPORT-004 failed"
    )
    service = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)
    request = await service.prepare(draft.id)

    receipt = await service.record_decision(
        draft_id=draft.id,
        actor_id=draft.created_by,
        action=ConfirmationAction.CONFIRM,
        request_payload_hash=request.request_payload_hash,
    )

    assert receipt.status is ToolConfirmationStatus.CONFIRMED
    assert receipt.request_payload_hash == request.request_payload_hash
    assert receipt.expires_at == draft.created_at + timedelta(minutes=15)


@pytest.mark.asyncio
async def test_confirmation_rejects_stale_or_tampered_payload_hash() -> None:
    now = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    draft = await drafts.create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=uuid4(), text="upload failed"
    )
    service = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)

    with pytest.raises(ConfirmationPayloadMismatch):
        await service.record_decision(
            draft_id=draft.id,
            actor_id=draft.created_by,
            action=ConfirmationAction.CONFIRM,
            request_payload_hash="0" * 64,
        )

    assert repo.confirmations == {}


@pytest.mark.asyncio
async def test_confirmation_exposes_frozen_evidence_without_changing_provider_payload_hash(
) -> None:
    now = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    evidence_ids = (str(uuid4()), str(uuid4()))
    draft = await repo.create_draft(
        IssueDraftCreate(
            run_id=uuid4(),
            project_id=uuid4(),
            created_by=uuid4(),
            title="ERR-IMPORT-004 failed",
            description="ERR-IMPORT-004 failed",
            issue_type="bug",
            proposed_priority="medium",
            evidence_ids=evidence_ids,
        )
    )
    service = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)

    create_request = drafts.build_create_request(draft)
    request = await service.prepare(draft.id)

    assert request.evidence_ids == evidence_ids
    assert request.request_payload_hash == drafts.payload_hash(create_request)
    assert not hasattr(create_request, "evidence_ids")

@pytest.mark.asyncio
async def test_confirmation_metrics_record_confirmed_and_payload_mismatch() -> None:
    from project_agent.observability.metrics import ObservabilityMetrics, metrics_context

    now = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
    repo = FakeIssueWorkflowRepository(clock=lambda: now)
    drafts = IssueDraftService(repo)
    draft = await drafts.create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=uuid4(), text="issue"
    )
    service = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)
    prepared = await service.prepare(draft.id)
    metrics = ObservabilityMetrics()
    with metrics_context(metrics):
        await service.record_decision(
            draft_id=draft.id,
            actor_id=draft.created_by,
            action=ConfirmationAction.CONFIRM,
            request_payload_hash=prepared.request_payload_hash,
        )
    rendered = metrics.render_latest().decode()
    assert 'project_agent_issue_confirmation_total{outcome="confirmed"} 1.0' in rendered

    other = await drafts.create_from_text(
        run_id=uuid4(), project_id=uuid4(), created_by=uuid4(), text="other"
    )
    with metrics_context(metrics), pytest.raises(ConfirmationPayloadMismatch):
        await service.record_decision(
            draft_id=other.id,
            actor_id=other.created_by,
            action=ConfirmationAction.CONFIRM,
            request_payload_hash="0" * 64,
        )
    rendered = metrics.render_latest().decode()
    assert 'project_agent_issue_confirmation_total{outcome="payload_mismatch"} 1.0' in rendered
