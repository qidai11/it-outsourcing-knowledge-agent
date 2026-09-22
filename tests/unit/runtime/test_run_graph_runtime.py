from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind
from project_agent.domain.runs import RunBusinessMode, RunRecord, RunStatus
from project_agent.runtime.run_graph import (
    ProductionRunGraphExecutor,
    build_production_run_graph_executor,
)
from project_agent.workers.run_graph import RunGraphUnavailable


def make_run(mode: RunBusinessMode) -> RunRecord:
    now = datetime.now(UTC)
    return RunRecord(
        id=uuid4(),
        thread_id=uuid4(),
        company_id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        business_mode=mode,
        status=RunStatus.RUNNING,
        started_at=now,
        finished_at=None,
    )


class RecordingExecutor:
    def __init__(self) -> None:
        self.execute_calls: list[RunRecord] = []
        self.resume_calls: list[tuple[RunRecord, dict[str, object]]] = []

    async def execute(self, run: RunRecord) -> RunGraphOutcome:
        self.execute_calls.append(run)
        return RunGraphOutcome(kind=RunGraphOutcomeKind.SUCCEEDED)

    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome:
        self.resume_calls.append((run, dict(resume_payload)))
        return RunGraphOutcome(kind=RunGraphOutcomeKind.SUCCEEDED)


class ClosableRecordingExecutor(RecordingExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_execute_routes_qa_to_qa_executor() -> None:
    qa = RecordingExecutor()
    issue = RecordingExecutor()
    executor = build_production_run_graph_executor(qa=qa, issue=issue)
    run = make_run(RunBusinessMode.QA)

    await executor.execute(run)

    assert qa.execute_calls == [run]
    assert issue.execute_calls == []


@pytest.mark.asyncio
async def test_execute_routes_issue_lookup_to_issue_executor() -> None:
    qa = RecordingExecutor()
    issue = RecordingExecutor()
    executor = ProductionRunGraphExecutor(qa=qa, issue=issue)
    run = make_run(RunBusinessMode.ISSUE_LOOKUP)

    await executor.execute(run)

    assert qa.execute_calls == []
    assert issue.execute_calls == [run]


@pytest.mark.asyncio
async def test_execute_routes_issue_create_to_issue_executor() -> None:
    qa = RecordingExecutor()
    issue = RecordingExecutor()
    executor = ProductionRunGraphExecutor(qa=qa, issue=issue)
    run = make_run(RunBusinessMode.ISSUE_CREATE)

    await executor.execute(run)

    assert qa.execute_calls == []
    assert issue.execute_calls == [run]


@pytest.mark.asyncio
async def test_resume_routes_issue_create_to_issue_executor() -> None:
    qa = RecordingExecutor()
    issue = RecordingExecutor()
    executor = ProductionRunGraphExecutor(qa=qa, issue=issue)
    run = make_run(RunBusinessMode.ISSUE_CREATE)
    payload: dict[str, object] = {"action": "confirm", "request_payload_hash": "abc"}

    await executor.resume(run, payload)

    assert qa.resume_calls == []
    assert issue.resume_calls == [(run, payload)]


@pytest.mark.asyncio
async def test_resume_rejects_qa_without_delegating() -> None:
    qa = RecordingExecutor()
    issue = RecordingExecutor()
    executor = ProductionRunGraphExecutor(qa=qa, issue=issue)
    run = make_run(RunBusinessMode.QA)

    with pytest.raises(RunGraphUnavailable, match="qa"):
        await executor.resume(run, {"action": "confirm"})

    assert qa.resume_calls == []
    assert issue.resume_calls == []


@pytest.mark.asyncio
async def test_aclose_closes_closable_child_executor_once() -> None:
    qa = RecordingExecutor()
    issue = ClosableRecordingExecutor()
    executor = ProductionRunGraphExecutor(qa=qa, issue=issue)

    await executor.aclose()

    assert issue.close_calls == 1
