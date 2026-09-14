from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class RunBusinessMode(StrEnum):
    QA = "qa"
    ISSUE_LOOKUP = "issue_lookup"
    ISSUE_CREATE = "issue_create"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    SUCCEEDED = "SUCCEEDED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class AgentEventType(StrEnum):
    RUN_QUEUED = "RUN_QUEUED"
    RUN_STARTED = "RUN_STARTED"
    RUN_PROGRESS = "RUN_PROGRESS"
    ARTIFACT_AVAILABLE = "ARTIFACT_AVAILABLE"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    RUN_RESUME_QUEUED = "RUN_RESUME_QUEUED"
    RUN_RESUMED = "RUN_RESUMED"
    RUN_SUCCEEDED = "RUN_SUCCEEDED"
    RUN_REFUSED = "RUN_REFUSED"
    RUN_CANCELLED = "RUN_CANCELLED"
    RUN_FAILED = "RUN_FAILED"


class RunJobType(StrEnum):
    EXECUTE = "EXECUTE_AGENT_RUN"
    RESUME = "RESUME_AGENT_RUN"


@dataclass(frozen=True, slots=True)
class ThreadRecord:
    id: UUID
    company_id: UUID
    project_id: UUID
    user_id: UUID
    title: str | None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: UUID
    thread_id: UUID
    company_id: UUID
    project_id: UUID
    user_id: UUID
    business_mode: RunBusinessMode
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    result_ref: str | None = None
    result_summary: str | None = None


@dataclass(frozen=True, slots=True)
class AgentEventRecord:
    id: UUID
    run_id: UUID
    sequence_no: int
    event_type: AgentEventType
    payload: dict[str, object]
    created_at: datetime | None = None


TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.REFUSED, RunStatus.CANCELLED, RunStatus.FAILED}
)
TERMINAL_EVENT_TYPES = frozenset(
    {
        AgentEventType.RUN_SUCCEEDED,
        AgentEventType.RUN_REFUSED,
        AgentEventType.RUN_CANCELLED,
        AgentEventType.RUN_FAILED,
    }
)
