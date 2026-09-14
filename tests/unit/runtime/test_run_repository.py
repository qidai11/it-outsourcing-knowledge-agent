from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.domain.runs import AgentEventType, RunBusinessMode, RunStatus
from project_agent.infrastructure.db.models.schema import AgentEventModel, AgentRunModel
from project_agent.infrastructure.db.repositories.runs import SqlAlchemyRunRepository


class ScalarRows:
    def __init__(self, *, one: object | None = None, many: list[object] | None = None) -> None:
        self._one = one
        self._many = many or []

    def one_or_none(self) -> object | None:
        return self._one

    def all(self) -> list[object]:
        return list(self._many)


class RepositorySession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.scalar_value: object | None = None
        self.scalar_rows: list[ScalarRows] = []
        self.get_value: object | None = None

    def add(self, row: object) -> None:
        self.added.append(row)
        if getattr(row, "id", None) is None:
            setattr(row, "id", uuid4())

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def get(self, _model: object, _key: UUID) -> object | None:
        return self.get_value

    async def scalars(self, _statement: object) -> ScalarRows:
        if not self.scalar_rows:
            raise AssertionError("unexpected scalars() call")
        return self.scalar_rows.pop(0)

    async def scalar(self, _statement: object) -> object | None:
        return self.scalar_value


def make_run_model(*, business_mode: str = "qa", status: str = "QUEUED") -> AgentRunModel:
    return AgentRunModel(
        id=uuid4(),
        thread_id=uuid4(),
        company_id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        business_mode=business_mode,
        status=status,
        started_at=None,
        finished_at=None,
    )


@pytest.mark.asyncio
async def test_sqlalchemy_run_repository_creates_queued_run_without_committing() -> None:
    session = RepositorySession()
    session.scalar_rows.append(ScalarRows(one=None))
    repository = SqlAlchemyRunRepository(cast(AsyncSession, session))

    created = await repository.create_run(
        thread_id=uuid4(),
        company_id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        business_mode=RunBusinessMode.QA,
    )

    row = cast(AgentRunModel, session.added[0])
    assert row.status == RunStatus.QUEUED.value
    assert row.business_mode == RunBusinessMode.QA.value
    assert row.started_at is None
    assert created.status is RunStatus.QUEUED
    assert created.business_mode is RunBusinessMode.QA
    assert session.flush_calls == 1
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_sqlalchemy_run_repository_appends_next_ordered_event_without_commit() -> None:
    session = RepositorySession()
    run_id = uuid4()
    session.scalar_rows.append(ScalarRows(one=run_id))
    session.scalar_value = 2
    repository = SqlAlchemyRunRepository(cast(AsyncSession, session))

    event = await repository.append_event(
        run_id=run_id,
        event_type=AgentEventType.RUN_PROGRESS,
        payload={"step": 3},
    )

    row = cast(AgentEventModel, session.added[0])
    assert row.run_id == run_id
    assert row.sequence_no == 3
    assert row.event_type == AgentEventType.RUN_PROGRESS.value
    assert event.sequence_no == 3
    assert event.payload == {"step": 3}
    assert session.flush_calls == 1
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_sqlalchemy_run_repository_exposes_only_safe_terminal_result_fields() -> None:
    session = RepositorySession()
    run = make_run_model(status=RunStatus.SUCCEEDED.value)
    terminal = AgentEventModel(
        id=uuid4(),
        run_id=run.id,
        sequence_no=4,
        event_type=AgentEventType.RUN_SUCCEEDED.value,
        payload_json={
            "result_ref": "answer:123",
            "summary": "done",
            "provider_secret": "must-not-leak",
        },
    )
    session.get_value = run
    session.scalar_rows.append(ScalarRows(one=terminal))
    repository = SqlAlchemyRunRepository(cast(AsyncSession, session))

    record = await repository.get_run(run.id)

    assert record is not None
    assert record.result_ref == "answer:123"
    assert record.result_summary == "done"
    assert not hasattr(record, "provider_secret")


@pytest.mark.asyncio
async def test_sqlalchemy_run_repository_rejects_legacy_run_without_business_mode() -> None:
    session = RepositorySession()
    run = make_run_model()
    run.business_mode = None
    session.get_value = run
    session.scalar_rows.append(ScalarRows(one=None))
    repository = SqlAlchemyRunRepository(cast(AsyncSession, session))

    with pytest.raises(ValueError, match="has no business_mode"):
        await repository.get_run(run.id)
