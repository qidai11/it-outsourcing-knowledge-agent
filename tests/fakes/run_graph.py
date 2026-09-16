from __future__ import annotations

from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind
from project_agent.domain.runs import RunRecord


class FakeRunGraphExecutor:
    def __init__(
        self,
        *,
        execute_outcome: RunGraphOutcome | None = None,
        resume_outcome: RunGraphOutcome | None = None,
    ) -> None:
        self.execute_outcome = execute_outcome or RunGraphOutcome(
            kind=RunGraphOutcomeKind.SUCCEEDED
        )
        self.resume_outcome = resume_outcome or RunGraphOutcome(
            kind=RunGraphOutcomeKind.SUCCEEDED
        )
        self.execute_calls: list[RunRecord] = []
        self.resume_calls: list[tuple[RunRecord, dict[str, object]]] = []

    async def execute(self, run: RunRecord) -> RunGraphOutcome:
        self.execute_calls.append(run)
        return self.execute_outcome

    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome:
        self.resume_calls.append((run, dict(resume_payload)))
        return self.resume_outcome
