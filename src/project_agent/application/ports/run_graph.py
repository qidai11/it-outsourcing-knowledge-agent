from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from project_agent.domain.runs import RunRecord


class RunGraphOutcomeKind(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class RunGraphOutcome:
    kind: RunGraphOutcomeKind
    result_ref: str | None = None
    summary: str | None = None
    waiting_payload: dict[str, object] | None = None


class RunGraphExecutor(Protocol):
    async def execute(self, run: RunRecord) -> RunGraphOutcome: ...

    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome: ...
