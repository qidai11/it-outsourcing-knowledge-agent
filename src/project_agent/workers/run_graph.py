from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from langgraph.types import Command, Interrupt

from project_agent.application.ports.run_graph import (
    RunGraphExecutor,
    RunGraphOutcome,
    RunGraphOutcomeKind,
)
from project_agent.domain.runs import RunBusinessMode, RunRecord


class RunGraphUnavailable(RuntimeError):
    """Raised when a Run business mode has no graph registered for execution."""


class RunGraphContractError(RuntimeError):
    """Raised when a graph result cannot be projected into the durable Run contract."""


class CompiledRunGraph(Protocol):
    async def ainvoke(
        self,
        input: object,
        config: dict[str, object],
    ) -> Mapping[str, object]: ...


class LangGraphRunExecutor(RunGraphExecutor):
    def __init__(self, graphs: Mapping[RunBusinessMode, CompiledRunGraph]) -> None:
        self._graphs = dict(graphs)

    async def execute(self, run: RunRecord) -> RunGraphOutcome:
        graph = self._graph_for(run)
        state: dict[str, object] = {
            "run_id": str(run.id),
            "thread_id": str(run.thread_id),
            "user_id": str(run.user_id),
            "project_id": str(run.project_id),
            "route": None,
            "last_error_code": None,
        }
        result = await graph.ainvoke(state, self._config(run))
        return self._project(result)

    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome:
        graph = self._graph_for(run)
        action = resume_payload.get("action")
        request_payload_hash = resume_payload.get("request_payload_hash")
        if not isinstance(action, str):
            raise RunGraphContractError("resume payload requires string action")
        if not isinstance(request_payload_hash, str):
            raise RunGraphContractError(
                "resume payload requires string request_payload_hash"
            )
        command: Command[str] = Command(
            resume={
                "action": action,
                "request_payload_hash": request_payload_hash,
            }
        )
        result = await graph.ainvoke(command, self._config(run))
        return self._project(result)

    def _graph_for(self, run: RunRecord) -> CompiledRunGraph:
        try:
            return self._graphs[run.business_mode]
        except KeyError as exc:
            raise RunGraphUnavailable(run.business_mode.value) from exc

    @staticmethod
    def _config(run: RunRecord) -> dict[str, object]:
        return {"configurable": {"thread_id": str(run.thread_id)}}

    @staticmethod
    def _project(result: Mapping[str, object]) -> RunGraphOutcome:
        if "__interrupt__" in result:
            raw_interrupts = result["__interrupt__"]
            if not isinstance(raw_interrupts, (tuple, list)) or len(raw_interrupts) != 1:
                raise RunGraphContractError(
                    "graph result must contain exactly one LangGraph interrupt"
                )
            interrupt = raw_interrupts[0]
            if not isinstance(interrupt, Interrupt):
                raise RunGraphContractError("graph interrupt has unexpected type")
            if not isinstance(interrupt.value, dict):
                raise RunGraphContractError("graph interrupt value must be a dict")
            return RunGraphOutcome(
                kind=RunGraphOutcomeKind.WAITING_CONFIRMATION,
                waiting_payload=dict(interrupt.value),
            )

        route = result.get("route")
        if route == "refusal":
            return RunGraphOutcome(
                kind=RunGraphOutcomeKind.REFUSED,
                result_ref=_string_value(result.get("answer_id")),
                summary=_string_value(result.get("last_error_code")),
            )
        if route == "cancelled":
            return RunGraphOutcome(kind=RunGraphOutcomeKind.CANCELLED)

        result_ref = next(
            (
                value
                for key in (
                    "answer_id",
                    "issue_candidate_id",
                    "issue_creation_id",
                    "issue_draft_id",
                )
                if (value := _string_value(result.get(key))) is not None
            ),
            None,
        )
        return RunGraphOutcome(
            kind=RunGraphOutcomeKind.SUCCEEDED,
            result_ref=result_ref,
        )


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None
