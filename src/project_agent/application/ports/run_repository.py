from __future__ import annotations

from typing import Protocol
from uuid import UUID

from project_agent.domain.runs import (
    AgentEventRecord,
    AgentEventType,
    RunBusinessMode,
    RunRecord,
    RunStatus,
    ThreadRecord,
)


class RunRepository(Protocol):
    async def get_thread(self, thread_id: UUID) -> ThreadRecord | None: ...

    async def create_thread(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        user_id: UUID,
        title: str | None = None,
    ) -> ThreadRecord: ...

    async def create_run(
        self,
        *,
        thread_id: UUID,
        company_id: UUID,
        project_id: UUID,
        user_id: UUID,
        business_mode: RunBusinessMode,
    ) -> RunRecord: ...

    async def get_run(
        self,
        run_id: UUID,
        *,
        for_update: bool = False,
    ) -> RunRecord | None: ...

    async def append_event(
        self,
        *,
        run_id: UUID,
        event_type: AgentEventType,
        payload: dict[str, object],
    ) -> AgentEventRecord: ...

    async def list_events_after(
        self,
        *,
        run_id: UUID,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[AgentEventRecord, ...]: ...

    async def latest_event_of_type(
        self,
        *,
        run_id: UUID,
        event_type: AgentEventType,
    ) -> AgentEventRecord | None: ...

    async def set_status(
        self,
        *,
        run_id: UUID,
        status: RunStatus,
    ) -> RunRecord: ...
