from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from tests.fakes.run_repository import FakeRunRepository

from project_agent.api.v1.runs import encode_sse_event, iter_sse_events, parse_last_event_id
from project_agent.domain.runs import (
    AgentEventRecord,
    AgentEventType,
    RunBusinessMode,
    RunRecord,
    RunStatus,
)


class CountingRunRepository(FakeRunRepository):
    def __init__(self) -> None:
        super().__init__()
        self.list_calls = 0
        self.get_calls = 0

    async def list_events_after(
        self,
        *,
        run_id: UUID,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[AgentEventRecord, ...]:
        self.list_calls += 1
        return await super().list_events_after(
            run_id=run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def get_run(
        self,
        run_id: UUID,
        *,
        for_update: bool = False,
    ) -> RunRecord | None:
        self.get_calls += 1
        return await super().get_run(run_id, for_update=for_update)


async def _seed_run(repository: FakeRunRepository) -> RunRecord:
    company_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    thread = await repository.create_thread(
        company_id=company_id,
        project_id=project_id,
        user_id=user_id,
    )
    return await repository.create_run(
        thread_id=thread.id,
        company_id=company_id,
        project_id=project_id,
        user_id=user_id,
        business_mode=RunBusinessMode.QA,
    )


def test_last_event_id_defaults_to_zero() -> None:
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id("") == 0


def test_last_event_id_rejects_malformed_or_negative() -> None:
    with pytest.raises(ValueError):
        parse_last_event_id("not-an-int")
    with pytest.raises(ValueError):
        parse_last_event_id("-1")
    with pytest.raises(ValueError):
        parse_last_event_id("+1")
    with pytest.raises(ValueError):
        parse_last_event_id(" 1")


def test_encode_sse_event_uses_sequence_type_and_compact_json() -> None:
    event = AgentEventRecord(
        id=uuid4(),
        run_id=uuid4(),
        sequence_no=7,
        event_type=AgentEventType.RUN_PROGRESS,
        payload={"message": "部署中", "percent": 50},
    )

    assert encode_sse_event(event) == (
        'id: 7\nevent: RUN_PROGRESS\ndata: {"message":"部署中","percent":50}\n\n'
    )


@pytest.mark.asyncio
async def test_iter_sse_events_orders_replays_and_stops_on_terminal_event() -> None:
    repository = CountingRunRepository()
    run = await _seed_run(repository)
    await repository.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_QUEUED,
        payload={"n": 1},
    )
    await repository.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_PROGRESS,
        payload={"n": 2},
    )
    await repository.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_SUCCEEDED,
        payload={"n": 3},
    )

    emitted = [
        chunk
        async for chunk in iter_sse_events(
            repository=repository,
            run_id=run.id,
            after_sequence=0,
        )
    ]
    replayed = [
        chunk
        async for chunk in iter_sse_events(
            repository=repository,
            run_id=run.id,
            after_sequence=1,
        )
    ]

    assert [chunk.splitlines()[0] for chunk in emitted] == ["id: 1", "id: 2", "id: 3"]
    assert [chunk.splitlines()[0] for chunk in replayed] == ["id: 2", "id: 3"]


@pytest.mark.asyncio
async def test_iter_sse_events_after_terminal_cursor_stops_without_sleeping() -> None:
    repository = CountingRunRepository()
    run = await _seed_run(repository)
    await repository.append_event(
        run_id=run.id,
        event_type=AgentEventType.RUN_SUCCEEDED,
        payload={},
    )
    await repository.set_status(run_id=run.id, status=RunStatus.SUCCEEDED)
    sleep_calls = 0

    async def sleep(_: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1

    emitted = [
        chunk
        async for chunk in iter_sse_events(
            repository=repository,
            run_id=run.id,
            after_sequence=1,
            sleep=sleep,
        )
    ]

    assert emitted == []
    assert sleep_calls == 0
    assert repository.get_calls == 1


@pytest.mark.asyncio
async def test_non_terminal_empty_poll_can_be_cancelled_without_mutation() -> None:
    repository = CountingRunRepository()
    run = await _seed_run(repository)
    before = repository.runs[run.id]
    before_events = tuple(repository.events[run.id])

    async def cancelled_sleep(_: float) -> None:
        raise asyncio.CancelledError

    stream = iter_sse_events(
        repository=repository,
        run_id=run.id,
        after_sequence=0,
        sleep=cancelled_sleep,
    )

    with pytest.raises(asyncio.CancelledError):
        await anext(stream)

    assert repository.runs[run.id] == before
    assert tuple(repository.events[run.id]) == before_events
    assert repository.list_calls == 1
    assert repository.get_calls == 1
