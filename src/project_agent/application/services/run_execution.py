from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID

from project_agent.application.ports.run_graph import RunGraphOutcome, RunGraphOutcomeKind
from project_agent.application.ports.run_repository import RunRepository
from project_agent.domain.runs import (
    TERMINAL_RUN_STATUSES,
    AgentEventType,
    RunRecord,
    RunStatus,
)


class RunExecutionContractError(RuntimeError):
    """Raised when graph/runtime data cannot be projected safely."""


@dataclass(frozen=True, slots=True)
class RunExecutionPreparation:
    run: RunRecord
    invoke: bool
    resume_payload: Mapping[str, object] | None = None


class RunExecutionService:
    def __init__(
        self,
        repository: RunRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    async def prepare_execute(self, run_id: UUID) -> RunExecutionPreparation:
        run = await self._require_run(run_id)
        if run.status is RunStatus.WAITING_CONFIRMATION or run.status in TERMINAL_RUN_STATUSES:
            return RunExecutionPreparation(run=run, invoke=False)

        queued = await self._repository.latest_event_of_type(
            run_id=run_id,
            event_type=AgentEventType.RUN_QUEUED,
        )
        if queued is None:
            return RunExecutionPreparation(run=run, invoke=False)

        resume_queued = await self._repository.latest_event_of_type(
            run_id=run_id,
            event_type=AgentEventType.RUN_RESUME_QUEUED,
        )
        resumed = await self._repository.latest_event_of_type(
            run_id=run_id,
            event_type=AgentEventType.RUN_RESUMED,
        )
        if any(
            event is not None and event.sequence_no > queued.sequence_no
            for event in (resume_queued, resumed)
        ):
            return RunExecutionPreparation(run=run, invoke=False)

        started = await self._repository.latest_event_of_type(
            run_id=run_id,
            event_type=AgentEventType.RUN_STARTED,
        )
        if run.status is RunStatus.QUEUED:
            run = await self._repository.set_lifecycle(
                run_id=run_id,
                status=RunStatus.RUNNING,
                started_at=run.started_at or self._clock(),
                finished_at=None,
            )
            if started is None or started.sequence_no < queued.sequence_no:
                await self._repository.append_event(
                    run_id=run_id,
                    event_type=AgentEventType.RUN_STARTED,
                    payload={},
                )
        elif run.status is not RunStatus.RUNNING:
            return RunExecutionPreparation(run=run, invoke=False)

        return RunExecutionPreparation(run=run, invoke=True)

    async def prepare_resume(self, run_id: UUID) -> RunExecutionPreparation:
        run = await self._require_run(run_id)
        if run.status is RunStatus.WAITING_CONFIRMATION or run.status in TERMINAL_RUN_STATUSES:
            return RunExecutionPreparation(run=run, invoke=False)
        if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            return RunExecutionPreparation(run=run, invoke=False)

        resume_queued = await self._repository.latest_event_of_type(
            run_id=run_id,
            event_type=AgentEventType.RUN_RESUME_QUEUED,
        )
        if resume_queued is None:
            return RunExecutionPreparation(run=run, invoke=False)

        started = await self._repository.latest_event_of_type(
            run_id=run_id,
            event_type=AgentEventType.RUN_STARTED,
        )
        if started is not None and resume_queued.sequence_no <= started.sequence_no:
            return RunExecutionPreparation(run=run, invoke=False)

        resumed = await self._repository.latest_event_of_type(
            run_id=run_id,
            event_type=AgentEventType.RUN_RESUMED,
        )
        if run.status is RunStatus.QUEUED:
            run = await self._repository.set_lifecycle(
                run_id=run_id,
                status=RunStatus.RUNNING,
                started_at=run.started_at,
                finished_at=None,
            )
        if resumed is None or resumed.sequence_no < resume_queued.sequence_no:
            await self._repository.append_event(
                run_id=run_id,
                event_type=AgentEventType.RUN_RESUMED,
                payload={},
            )

        payload = MappingProxyType(dict(resume_queued.payload))
        return RunExecutionPreparation(run=run, invoke=True, resume_payload=payload)

    async def persist_outcome(self, run_id: UUID, outcome: RunGraphOutcome) -> RunRecord:
        run = await self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES or run.status is RunStatus.WAITING_CONFIRMATION:
            return run

        if outcome.kind is RunGraphOutcomeKind.WAITING_CONFIRMATION:
            waiting_payload = outcome.waiting_payload
            if waiting_payload is None:
                raise RunExecutionContractError(
                    "WAITING_CONFIRMATION requires string request_payload_hash"
                )
            request_hash = waiting_payload.get("request_payload_hash")
            if not isinstance(request_hash, str):
                raise RunExecutionContractError(
                    "WAITING_CONFIRMATION requires string request_payload_hash"
                )
            run = await self._repository.set_lifecycle(
                run_id=run_id,
                status=RunStatus.WAITING_CONFIRMATION,
                started_at=run.started_at,
                finished_at=None,
            )
            await self._repository.append_event(
                run_id=run_id,
                event_type=AgentEventType.WAITING_CONFIRMATION,
                payload=dict(waiting_payload),
            )
            return run

        status, event_type = _terminal_projection(outcome.kind)
        run = await self._repository.set_lifecycle(
            run_id=run_id,
            status=status,
            started_at=run.started_at,
            finished_at=self._clock(),
        )
        payload: dict[str, object] = {}
        if outcome.result_ref is not None:
            payload["result_ref"] = outcome.result_ref
        if outcome.summary is not None:
            payload["summary"] = outcome.summary
        await self._repository.append_event(
            run_id=run_id,
            event_type=event_type,
            payload=payload,
        )
        return run

    async def mark_final_failure(self, run_id: UUID, error_code: str) -> RunRecord:
        run = await self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return run
        run = await self._repository.set_lifecycle(
            run_id=run_id,
            status=RunStatus.FAILED,
            started_at=run.started_at,
            finished_at=self._clock(),
        )
        await self._repository.append_event(
            run_id=run_id,
            event_type=AgentEventType.RUN_FAILED,
            payload={"error_code": error_code},
        )
        return run

    async def _require_run(self, run_id: UUID) -> RunRecord:
        run = await self._repository.get_run(run_id, for_update=True)
        if run is None:
            raise LookupError(run_id)
        return run


def _terminal_projection(
    kind: RunGraphOutcomeKind,
) -> tuple[RunStatus, AgentEventType]:
    if kind is RunGraphOutcomeKind.SUCCEEDED:
        return RunStatus.SUCCEEDED, AgentEventType.RUN_SUCCEEDED
    if kind is RunGraphOutcomeKind.REFUSED:
        return RunStatus.REFUSED, AgentEventType.RUN_REFUSED
    if kind is RunGraphOutcomeKind.CANCELLED:
        return RunStatus.CANCELLED, AgentEventType.RUN_CANCELLED
    raise RunExecutionContractError(f"unsupported terminal graph outcome: {kind.value}")
