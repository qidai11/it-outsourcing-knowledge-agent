from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from project_agent.domain.runs import (
    TERMINAL_EVENT_TYPES,
    TERMINAL_RUN_STATUSES,
    AgentEventType,
    RunBusinessMode,
    RunJobType,
    RunStatus,
    ThreadRecord,
)


def test_ws2_run_vocabulary_is_stable() -> None:
    assert tuple(mode.value for mode in RunBusinessMode) == (
        "qa",
        "issue_lookup",
        "issue_create",
    )
    assert tuple(status.value for status in RunStatus) == (
        "QUEUED",
        "RUNNING",
        "WAITING_CONFIRMATION",
        "SUCCEEDED",
        "REFUSED",
        "CANCELLED",
        "FAILED",
    )
    assert tuple(event.value for event in AgentEventType) == (
        "RUN_QUEUED",
        "RUN_STARTED",
        "RUN_PROGRESS",
        "ARTIFACT_AVAILABLE",
        "WAITING_CONFIRMATION",
        "RUN_RESUME_QUEUED",
        "RUN_RESUMED",
        "RUN_SUCCEEDED",
        "RUN_REFUSED",
        "RUN_CANCELLED",
        "RUN_FAILED",
    )
    assert tuple(job.value for job in RunJobType) == (
        "EXECUTE_AGENT_RUN",
        "RESUME_AGENT_RUN",
    )


def test_terminal_sets_only_contain_terminal_values() -> None:
    assert frozenset(
        {RunStatus.SUCCEEDED, RunStatus.REFUSED, RunStatus.CANCELLED, RunStatus.FAILED}
    ) == TERMINAL_RUN_STATUSES
    assert frozenset(
        {
            AgentEventType.RUN_SUCCEEDED,
            AgentEventType.RUN_REFUSED,
            AgentEventType.RUN_CANCELLED,
            AgentEventType.RUN_FAILED,
        }
    ) == TERMINAL_EVENT_TYPES


def test_thread_record_is_frozen() -> None:
    record = ThreadRecord(
        id=uuid4(),
        company_id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        title=None,
    )
    with pytest.raises(FrozenInstanceError):
        record.title = "changed"  # type: ignore[misc]
