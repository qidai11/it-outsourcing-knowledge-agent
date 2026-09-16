from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from langgraph.types import Command, Interrupt

from project_agent.application.ports.run_graph import RunGraphOutcomeKind
from project_agent.domain.runs import RunBusinessMode, RunRecord, RunStatus
from project_agent.workers.run_graph import (
    LangGraphRunExecutor,
    RunGraphContractError,
    RunGraphUnavailable,
)

HASH = "a" * 64


@dataclass
class Call:
    input: object
    config: dict[str, object]


class RecordingGraph:
    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result or {}
        self.calls: list[Call] = []

    async def ainvoke(self, input: object, config: dict[str, object]) -> dict[str, object]:
        self.calls.append(Call(input=input, config=config))
        return dict(self.result)


def make_run(*, business_mode: RunBusinessMode = RunBusinessMode.QA) -> RunRecord:
    return RunRecord(
        id=uuid4(),
        thread_id=uuid4(),
        company_id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        business_mode=business_mode,
        status=RunStatus.RUNNING,
        started_at=None,
        finished_at=None,
    )


@pytest.mark.asyncio
async def test_execute_uses_checkpoint_safe_ids_and_thread_identity() -> None:
    run = make_run()
    graph = RecordingGraph({"answer_id": "answer:1"})
    executor = LangGraphRunExecutor({RunBusinessMode.QA: graph})

    outcome = await executor.execute(run)

    assert outcome.kind is RunGraphOutcomeKind.SUCCEEDED
    assert outcome.result_ref == "answer:1"
    assert len(graph.calls) == 1
    assert graph.calls[0].input == {
        "run_id": str(run.id),
        "thread_id": str(run.thread_id),
        "user_id": str(run.user_id),
        "project_id": str(run.project_id),
        "route": None,
        "last_error_code": None,
    }
    assert graph.calls[0].config == {
        "configurable": {"thread_id": str(run.thread_id)}
    }


@pytest.mark.asyncio
async def test_resume_uses_real_command_with_filtered_resume_value_and_same_thread() -> None:
    run = make_run(business_mode=RunBusinessMode.ISSUE_CREATE)
    graph = RecordingGraph({"issue_creation_id": "issue-create:1"})
    executor = LangGraphRunExecutor({RunBusinessMode.ISSUE_CREATE: graph})
    durable = {
        "action": "confirm",
        "request_payload_hash": HASH,
        "actor_id": str(run.user_id),
    }

    outcome = await executor.resume(run, durable)

    assert outcome.kind is RunGraphOutcomeKind.SUCCEEDED
    assert len(graph.calls) == 1
    command = graph.calls[0].input
    assert isinstance(command, Command)
    assert command.resume == {
        "action": "confirm",
        "request_payload_hash": HASH,
    }
    assert graph.calls[0].config == {
        "configurable": {"thread_id": str(run.thread_id)}
    }
    assert durable["actor_id"] == str(run.user_id)


@pytest.mark.asyncio
async def test_unavailable_business_mode_is_visible_failure() -> None:
    run = make_run(business_mode=RunBusinessMode.ISSUE_LOOKUP)
    executor = LangGraphRunExecutor({})

    with pytest.raises(RunGraphUnavailable, match="issue_lookup"):
        await executor.execute(run)


@pytest.mark.asyncio
async def test_single_dict_interrupt_projects_waiting_confirmation() -> None:
    run = make_run(business_mode=RunBusinessMode.ISSUE_CREATE)
    payload = {"request_payload_hash": HASH, "tool_name": "create_issue"}
    graph = RecordingGraph({"__interrupt__": (Interrupt(value=payload, id="i1"),)})
    executor = LangGraphRunExecutor({RunBusinessMode.ISSUE_CREATE: graph})

    outcome = await executor.execute(run)

    assert outcome.kind is RunGraphOutcomeKind.WAITING_CONFIRMATION
    assert outcome.waiting_payload == payload
    assert outcome.waiting_payload is not payload


@pytest.mark.asyncio
async def test_multiple_interrupts_are_contract_error() -> None:
    run = make_run()
    graph = RecordingGraph(
        {
            "__interrupt__": (
                Interrupt(value={"request_payload_hash": HASH}, id="i1"),
                Interrupt(value={"request_payload_hash": HASH}, id="i2"),
            )
        }
    )
    executor = LangGraphRunExecutor({RunBusinessMode.QA: graph})

    with pytest.raises(RunGraphContractError, match="exactly one"):
        await executor.execute(run)


@pytest.mark.asyncio
async def test_non_dict_interrupt_value_is_contract_error() -> None:
    run = make_run()
    graph = RecordingGraph({"__interrupt__": (Interrupt(value="unsafe", id="i1"),)})
    executor = LangGraphRunExecutor({RunBusinessMode.QA: graph})

    with pytest.raises(RunGraphContractError, match="dict"):
        await executor.execute(run)


@pytest.mark.asyncio
async def test_refusal_projects_answer_reference_and_error_summary() -> None:
    run = make_run()
    graph = RecordingGraph(
        {"route": "refusal", "answer_id": "answer:refused", "last_error_code": "POLICY"}
    )
    executor = LangGraphRunExecutor({RunBusinessMode.QA: graph})

    outcome = await executor.execute(run)

    assert outcome.kind is RunGraphOutcomeKind.REFUSED
    assert outcome.result_ref == "answer:refused"
    assert outcome.summary == "POLICY"


@pytest.mark.asyncio
async def test_cancelled_route_projects_cancelled() -> None:
    run = make_run()
    graph = RecordingGraph({"route": "cancelled"})
    executor = LangGraphRunExecutor({RunBusinessMode.QA: graph})

    outcome = await executor.execute(run)

    assert outcome.kind is RunGraphOutcomeKind.CANCELLED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"answer_id": "answer:1", "issue_candidate_id": "candidate:1"}, "answer:1"),
        ({"issue_candidate_id": "candidate:1", "issue_creation_id": "create:1"}, "candidate:1"),
        ({"issue_creation_id": "create:1", "issue_draft_id": "draft:1"}, "create:1"),
        ({"issue_draft_id": "draft:1"}, "draft:1"),
        ({}, None),
    ],
)
async def test_success_projects_first_supported_result_reference(
    result: dict[str, object],
    expected: str | None,
) -> None:
    run = make_run()
    graph = RecordingGraph(result)
    executor = LangGraphRunExecutor({RunBusinessMode.QA: graph})

    outcome = await executor.execute(run)

    assert outcome.kind is RunGraphOutcomeKind.SUCCEEDED
    assert outcome.result_ref == expected
