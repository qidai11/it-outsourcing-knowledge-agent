from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.ports.run_repository import RunRepository
from project_agent.domain.runs import (
    AgentEventRecord,
    AgentEventType,
    RunBusinessMode,
    RunRecord,
    RunStatus,
    TERMINAL_EVENT_TYPES,
    ThreadRecord,
)
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    ThreadModel,
)


class SqlAlchemyRunRepository(RunRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_thread(self, thread_id: UUID) -> ThreadRecord | None:
        row = await self._session.get(ThreadModel, thread_id)
        return None if row is None else self._to_thread(row)

    async def create_thread(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        user_id: UUID,
        title: str | None = None,
    ) -> ThreadRecord:
        row = ThreadModel(
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
            title=title,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_thread(row)

    async def create_run(
        self,
        *,
        thread_id: UUID,
        company_id: UUID,
        project_id: UUID,
        user_id: UUID,
        business_mode: RunBusinessMode,
    ) -> RunRecord:
        row = AgentRunModel(
            thread_id=thread_id,
            company_id=company_id,
            project_id=project_id,
            user_id=user_id,
            business_mode=business_mode.value,
            status=RunStatus.QUEUED.value,
            started_at=None,
            finished_at=None,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_run(row)

    async def get_run(
        self,
        run_id: UUID,
        *,
        for_update: bool = False,
    ) -> RunRecord | None:
        if for_update:
            stmt = select(AgentRunModel).where(AgentRunModel.id == run_id).with_for_update()
            row = (await self._session.scalars(stmt)).one_or_none()
        else:
            row = await self._session.get(AgentRunModel, run_id)
        if row is None:
            return None
        terminal = await self._latest_terminal_event(run_id)
        return self._to_run(row, terminal=terminal)

    async def append_event(
        self,
        *,
        run_id: UUID,
        event_type: AgentEventType,
        payload: dict[str, object],
    ) -> AgentEventRecord:
        lock_stmt = select(AgentRunModel.id).where(AgentRunModel.id == run_id).with_for_update()
        locked_run_id = (await self._session.scalars(lock_stmt)).one_or_none()
        if locked_run_id is None:
            raise LookupError(run_id)

        sequence_stmt = select(func.max(AgentEventModel.sequence_no)).where(
            AgentEventModel.run_id == run_id
        )
        current_max = await self._session.scalar(sequence_stmt)
        row = AgentEventModel(
            run_id=run_id,
            sequence_no=(int(current_max) if current_max is not None else 0) + 1,
            event_type=event_type.value,
            payload_json=dict(payload),
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_event(row)

    async def list_events_after(
        self,
        *,
        run_id: UUID,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[AgentEventRecord, ...]:
        if limit < 1:
            return ()
        stmt = (
            select(AgentEventModel)
            .where(
                AgentEventModel.run_id == run_id,
                AgentEventModel.sequence_no > after_sequence,
            )
            .order_by(AgentEventModel.sequence_no.asc())
            .limit(limit)
        )
        rows = (await self._session.scalars(stmt)).all()
        return tuple(self._to_event(row) for row in rows)

    async def latest_event_of_type(
        self,
        *,
        run_id: UUID,
        event_type: AgentEventType,
    ) -> AgentEventRecord | None:
        stmt = (
            select(AgentEventModel)
            .where(
                AgentEventModel.run_id == run_id,
                AgentEventModel.event_type == event_type.value,
            )
            .order_by(AgentEventModel.sequence_no.desc())
            .limit(1)
        )
        row = (await self._session.scalars(stmt)).one_or_none()
        return None if row is None else self._to_event(row)

    async def set_status(
        self,
        *,
        run_id: UUID,
        status: RunStatus,
    ) -> RunRecord:
        stmt = select(AgentRunModel).where(AgentRunModel.id == run_id).with_for_update()
        row = (await self._session.scalars(stmt)).one_or_none()
        if row is None:
            raise LookupError(run_id)
        row.status = status.value
        await self._session.flush()
        return self._to_run(row)

    async def _latest_terminal_event(self, run_id: UUID) -> AgentEventModel | None:
        terminal_values = tuple(event_type.value for event_type in TERMINAL_EVENT_TYPES)
        stmt = (
            select(AgentEventModel)
            .where(
                AgentEventModel.run_id == run_id,
                AgentEventModel.event_type.in_(terminal_values),
            )
            .order_by(AgentEventModel.sequence_no.desc())
            .limit(1)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    @staticmethod
    def _to_run(
        row: AgentRunModel,
        *,
        terminal: AgentEventModel | None = None,
    ) -> RunRecord:
        if row.business_mode is None:
            raise ValueError(f"agent run {row.id} has no business_mode")
        result_ref: str | None = None
        result_summary: str | None = None
        if terminal is not None:
            raw_ref = terminal.payload_json.get("result_ref")
            raw_summary = terminal.payload_json.get("summary")
            result_ref = raw_ref if isinstance(raw_ref, str) else None
            result_summary = raw_summary if isinstance(raw_summary, str) else None
        return RunRecord(
            id=row.id,
            thread_id=row.thread_id,
            company_id=row.company_id,
            project_id=row.project_id,
            user_id=row.user_id,
            business_mode=RunBusinessMode(row.business_mode),
            status=RunStatus(row.status),
            started_at=row.started_at,
            finished_at=row.finished_at,
            result_ref=result_ref,
            result_summary=result_summary,
        )

    @staticmethod
    def _to_thread(row: ThreadModel) -> ThreadRecord:
        return ThreadRecord(
            id=row.id,
            company_id=row.company_id,
            project_id=row.project_id,
            user_id=row.user_id,
            title=row.title,
            created_at=row.created_at,
        )

    @staticmethod
    def _to_event(row: AgentEventModel) -> AgentEventRecord:
        return AgentEventRecord(
            id=row.id,
            run_id=row.run_id,
            sequence_no=row.sequence_no,
            event_type=AgentEventType(row.event_type),
            payload=dict(row.payload_json),
            created_at=row.created_at,
        )
