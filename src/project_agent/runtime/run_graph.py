from __future__ import annotations

from project_agent.application.ports.run_graph import (
    RunGraphExecutor,
    RunGraphOutcome,
)
from project_agent.domain.runs import RunBusinessMode, RunRecord
from project_agent.workers.run_graph import RunGraphUnavailable


class ProductionRunGraphExecutor(RunGraphExecutor):
    """Route durable Runs to the existing QA or Issue production executors."""

    def __init__(self, *, qa: RunGraphExecutor, issue: RunGraphExecutor) -> None:
        self._qa = qa
        self._issue = issue

    async def execute(self, run: RunRecord) -> RunGraphOutcome:
        return await self._for_mode(run.business_mode).execute(run)

    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome:
        if run.business_mode is RunBusinessMode.QA:
            raise RunGraphUnavailable(run.business_mode.value)
        return await self._for_mode(run.business_mode).resume(run, resume_payload)

    async def aclose(self) -> None:
        seen: set[int] = set()
        for executor in (self._qa, self._issue):
            identity = id(executor)
            if identity in seen:
                continue
            seen.add(identity)
            close = getattr(executor, "aclose", None)
            if callable(close):
                await close()

    def _for_mode(self, mode: RunBusinessMode) -> RunGraphExecutor:
        if mode is RunBusinessMode.QA:
            return self._qa
        if mode in {RunBusinessMode.ISSUE_LOOKUP, RunBusinessMode.ISSUE_CREATE}:
            return self._issue
        raise RunGraphUnavailable(str(mode))


def build_production_run_graph_executor(
    *,
    qa: RunGraphExecutor,
    issue: RunGraphExecutor,
) -> ProductionRunGraphExecutor:
    return ProductionRunGraphExecutor(qa=qa, issue=issue)
