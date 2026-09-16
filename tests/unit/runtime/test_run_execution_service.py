from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

import pytest
from tests.fakes.run_repository import FakeRunRepository

from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind
from project_agent.application.services.run_execution import (
    RunExecutionContractError,
    RunExecutionService,
)
from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunStatus

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
HASH = "a" * 64


async def seeded_run(*, status: RunStatus = RunStatus.QUEUED):
    repo = FakeRunRepository()
    thread = await repo.create_thread(
        company_id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
    )
    run = await repo.create_run(
        thread_id=thread.id,
        company_id=thread.company_id,
        project_id=thread.project_id,
        user_id=thread.user_id,
        business_mode=RunBusinessMode.ISSUE_CREATE,
    )
    if status is not RunStatus.QUEUED:
        repo.runs[run.id] = replace(run, status=status)
        run = repo.runs[run.id]
    return repo, run


@pytest.mark.asyncio
async def test_prepare_execute_marks_started_once_and_retry_reuses_running_run() -> None:
    repo, run = await seeded_run()
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"query_text": "hello"},
    )
    service = RunExecutionService(repo, clock=lambda: NOW)

    first = await service.prepare_execute(run.id)
    second = await service.prepare_execute(run.id)

    assert first.invoke is True
    assert second.invoke is True
    assert repo.runs[run.id].status is RunStatus.RUNNING
    assert repo.runs[run.id].started_at == NOW
    assert [e.event_type for e in repo.events[run.id]].count(AgentEventType.RUN_STARTED) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        RunStatus.WAITING_CONFIRMATION,
        RunStatus.SUCCEEDED,
        RunStatus.REFUSED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    ],
)
async def test_prepare_execute_does_not_invoke_waiting_or_terminal_run(status: RunStatus) -> None:
    repo, run = await seeded_run(status=status)
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"query_text": "hello"},
    )
    service = RunExecutionService(repo, clock=lambda: NOW)

    preparation = await service.prepare_execute(run.id)

    assert preparation.invoke is False
    assert repo.runs[run.id].status is status
    assert all(event.event_type is not AgentEventType.RUN_STARTED for event in repo.events[run.id])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "superseding_event",
    [AgentEventType.RUN_RESUME_QUEUED, AgentEventType.RUN_RESUMED],
)
async def test_prepare_execute_ignores_stale_job_after_newer_resume_intent(
    superseding_event: AgentEventType,
) -> None:
    repo, run = await seeded_run(status=RunStatus.RUNNING)
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"query_text": "hello"},
    )
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_STARTED,
        payload={},
    )
    payload = (
        {
            "action": "confirm",
            "request_payload_hash": HASH,
            "actor_id": str(run.user_id),
        }
        if superseding_event is AgentEventType.RUN_RESUME_QUEUED
        else {}
    )
    await repo.append_event(
        run_id=run.id,
        event_type=superseding_event,
        payload=payload,
    )
    service = RunExecutionService(repo, clock=lambda: NOW)

    preparation = await service.prepare_execute(run.id)

    assert preparation.invoke is False
    assert [e.event_type for e in repo.events[run.id]].count(AgentEventType.RUN_STARTED) == 1


@pytest.mark.asyncio
async def test_prepare_resume_requires_durable_resume_intent() -> None:
    repo, run = await seeded_run()
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"query_text": "hello"},
    )
    service = RunExecutionService(repo, clock=lambda: NOW)

    preparation = await service.prepare_resume(run.id)

    assert preparation.invoke is False
    assert preparation.resume_payload is None
    assert all(event.event_type is not AgentEventType.RUN_RESUMED for event in repo.events[run.id])


@pytest.mark.asyncio
async def test_prepare_resume_emits_once_and_exposes_immutable_durable_payload() -> None:
    repo, run = await seeded_run(status=RunStatus.QUEUED)
    repo.runs[run.id] = replace(run, started_at=NOW)
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"query_text": "hello"},
    )
    await repo.append_event(run_id=run.id, event_type=AgentEventType.RUN_STARTED, payload={})
    durable = {
        "action": "confirm",
        "request_payload_hash": HASH,
        "actor_id": str(run.user_id),
        "audit_note": "durable",
    }
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_RESUME_QUEUED,
        payload=durable,
    )
    service = RunExecutionService(repo, clock=lambda: NOW)

    first = await service.prepare_resume(run.id)
    second = await service.prepare_resume(run.id)

    assert first.invoke is True
    assert second.invoke is True
    assert isinstance(first.resume_payload, MappingProxyType)
    assert dict(first.resume_payload) == durable
    assert first.resume_payload is not repo.events[run.id][-2].payload
    with pytest.raises(TypeError):
        first.resume_payload["action"] = "cancel"  # type: ignore[index]
    assert repo.events[run.id][-2].payload == durable
    assert repo.runs[run.id].status is RunStatus.RUNNING
    assert repo.runs[run.id].started_at == NOW
    assert [e.event_type for e in repo.events[run.id]].count(AgentEventType.RUN_RESUMED) == 1


@pytest.mark.asyncio
async def test_prepare_resume_rejects_intent_older_than_latest_run_started() -> None:
    repo, run = await seeded_run(status=RunStatus.RUNNING)
    await repo.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_RESUME_QUEUED,
        payload={"action": "confirm", "request_payload_hash": HASH, "actor_id": str(run.user_id)},
    )
    await repo.append_event(run_id=run.id, event_type=AgentEventType.RUN_STARTED, payload={})
    service = RunExecutionService(repo, clock=lambda: NOW)

    preparation = await service.prepare_resume(run.id)

    assert preparation.invoke is False
    assert all(event.event_type is not AgentEventType.RUN_RESUMED for event in repo.events[run.id])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status", "event_type"),
    [
        (RunGraphOutcomeKind.SUCCEEDED, RunStatus.SUCCEEDED, AgentEventType.RUN_SUCCEEDED),
        (RunGraphOutcomeKind.REFUSED, RunStatus.REFUSED, AgentEventType.RUN_REFUSED),
        (RunGraphOutcomeKind.CANCELLED, RunStatus.CANCELLED, AgentEventType.RUN_CANCELLED),
    ],
)
async def test_persist_terminal_outcome_sets_finished_at_and_event_once(
    kind: RunGraphOutcomeKind,
    status: RunStatus,
    event_type: AgentEventType,
) -> None:
    repo, run = await seeded_run(status=RunStatus.RUNNING)
    service = RunExecutionService(repo, clock=lambda: NOW)
    outcome = RunGraphOutcome(kind=kind, result_ref="result:1", summary="done")

    await service.persist_outcome(run.id, outcome)
    await service.persist_outcome(run.id, outcome)

    persisted = repo.runs[run.id]
    assert persisted.status is status
    assert persisted.finished_at == NOW
    terminal_events = [event for event in repo.events[run.id] if event.event_type is event_type]
    assert len(terminal_events) == 1
    assert terminal_events[0].payload == {"result_ref": "result:1", "summary": "done"}


@pytest.mark.asyncio
async def test_persist_waiting_confirmation_keeps_finished_at_null() -> None:
    repo, run = await seeded_run(status=RunStatus.RUNNING)
    service = RunExecutionService(repo, clock=lambda: NOW)
    outcome = RunGraphOutcome(
        kind=RunGraphOutcomeKind.WAITING_CONFIRMATION,
        waiting_payload={"request_payload_hash": HASH, "tool_name": "create_issue"},
    )

    await service.persist_outcome(run.id, outcome)
    await service.persist_outcome(run.id, outcome)

    persisted = repo.runs[run.id]
    assert persisted.status is RunStatus.WAITING_CONFIRMATION
    assert persisted.finished_at is None
    waiting = [
        event
        for event in repo.events[run.id]
        if event.event_type is AgentEventType.WAITING_CONFIRMATION
    ]
    assert len(waiting) == 1
    assert waiting[0].payload == {
        "request_payload_hash": HASH,
        "tool_name": "create_issue",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, {}, {"request_payload_hash": 123}])
async def test_persist_waiting_confirmation_rejects_invalid_hash_without_mutation(
    payload: dict[str, object] | None,
) -> None:
    repo, run = await seeded_run(status=RunStatus.RUNNING)
    service = RunExecutionService(repo, clock=lambda: NOW)

    with pytest.raises(RunExecutionContractError, match="request_payload_hash"):
        await service.persist_outcome(
            run.id,
            RunGraphOutcome(
                kind=RunGraphOutcomeKind.WAITING_CONFIRMATION,
                waiting_payload=payload,
            ),
        )

    assert repo.runs[run.id].status is RunStatus.RUNNING
    assert repo.runs[run.id].finished_at is None
    assert repo.events[run.id] == []


@pytest.mark.asyncio
async def test_mark_final_failure_is_idempotent_and_persists_error_code_only() -> None:
    repo, run = await seeded_run(status=RunStatus.RUNNING)
    service = RunExecutionService(repo, clock=lambda: NOW)

    await service.mark_final_failure(run.id, "TimeoutError")
    await service.mark_final_failure(run.id, "DifferentError")

    persisted = repo.runs[run.id]
    assert persisted.status is RunStatus.FAILED
    assert persisted.finished_at == NOW
    failures = [
        event
        for event in repo.events[run.id]
        if event.event_type is AgentEventType.RUN_FAILED
    ]
    assert len(failures) == 1
    assert failures[0].payload == {"error_code": "TimeoutError"}
