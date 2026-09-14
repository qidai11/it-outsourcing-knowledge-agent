from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

from project_agent.domain.runs import (
    TERMINAL_EVENT_TYPES,
    AgentEventRecord,
    AgentEventType,
    RunBusinessMode,
    RunRecord,
    RunStatus,
    ThreadRecord,
)


class FakeRunRepository:
    def __init__(self) -> None:
        self.threads: dict[UUID, ThreadRecord] = {}
        self.runs: dict[UUID, RunRecord] = {}
        self.events: dict[UUID, list[AgentEventRecord]] = {}

    async def get_thread(self, thread_id: UUID) -> ThreadRecord | None:
        return self.threads.get(thread_id)

    async def create_thread(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        user_id: UUID,
        title: str | None = None,
    ) -> ThreadRecord:
        record = ThreadRecord(
            id=uuid4(),
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
            title=title,
        )
        self.threads[record.id] = record
        return record

    async def create_run(
        self,
        *,
        thread_id: UUID,
        company_id: UUID,
        project_id: UUID,
        user_id: UUID,
        business_mode: RunBusinessMode,
    ) -> RunRecord:
        if thread_id not in self.threads:
            raise LookupError(thread_id)
        record = RunRecord(
            id=uuid4(),
            thread_id=thread_id,
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
            business_mode=business_mode,
            status=RunStatus.QUEUED,
            started_at=None,
            finished_at=None,
        )
        self.runs[record.id] = record
        self.events[record.id] = []
        return record

    async def get_run(
        self,
        run_id: UUID,
        *,
        for_update: bool = False,
    ) -> RunRecord | None:
        del for_update
        record = self.runs.get(run_id)
        if record is None:
            return None
        return self._with_terminal_result(record)

    async def append_event(
        self,
        *,
        run_id: UUID,
        event_type: AgentEventType,
        payload: dict[str, object],
    ) -> AgentEventRecord:
        if run_id not in self.runs:
            raise LookupError(run_id)
        rows = self.events.setdefault(run_id, [])
        next_sequence = max((event.sequence_no for event in rows), default=0) + 1
        record = AgentEventRecord(
            id=uuid4(),
            run_id=run_id,
            sequence_no=next_sequence,
            event_type=event_type,
            payload=dict(payload),
        )
        rows.append(record)
        return record

    async def list_events_after(
        self,
        *,
        run_id: UUID,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[AgentEventRecord, ...]:
        if limit < 1:
            return ()
        rows = sorted(self.events.get(run_id, ()), key=lambda event: event.sequence_no)
        return tuple(event for event in rows if event.sequence_no > after_sequence)[:limit]

    async def latest_event_of_type(
        self,
        *,
        run_id: UUID,
        event_type: AgentEventType,
    ) -> AgentEventRecord | None:
        for event in reversed(self.events.get(run_id, ())):
            if event.event_type is event_type:
                return event
        return None

    async def set_status(
        self,
        *,
        run_id: UUID,
        status: RunStatus,
    ) -> RunRecord:
        current = self.runs.get(run_id)
        if current is None:
            raise LookupError(run_id)
        updated = replace(current, status=status)
        self.runs[run_id] = updated
        return self._with_terminal_result(updated)

    def _with_terminal_result(self, record: RunRecord) -> RunRecord:
        terminal = next(
            (
                event
                for event in reversed(self.events.get(record.id, ()))
                if event.event_type in TERMINAL_EVENT_TYPES
            ),
            None,
        )
        if terminal is None:
            return record
        result_ref = terminal.payload.get("result_ref")
        summary = terminal.payload.get("summary")
        return replace(
            record,
            result_ref=result_ref if isinstance(result_ref, str) else None,
            result_summary=summary if isinstance(summary, str) else None,
        )
