from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.infrastructure.db.repositories.qa_graph import SqlAlchemyQAGraphStore


class ScalarResult:
    def __init__(self, payload: dict[str, object] | None) -> None:
        self._payload = payload

    def scalar_one_or_none(self) -> dict[str, object] | None:
        return self._payload


class RecordingSession:
    def __init__(self, payload: dict[str, object] | None) -> None:
        self.payload = payload
        self.statement: Any | None = None

    async def execute(self, statement: Any) -> ScalarResult:
        self.statement = statement
        return ScalarResult(self.payload)


@pytest.mark.asyncio
async def test_load_query_accepts_ws2_run_queued_event_and_legacy_user_query() -> None:
    session = RecordingSession({"query_text": "durable question"})
    store = SqlAlchemyQAGraphStore(cast(AsyncSession, session))

    assert await store.load_query(uuid4()) == "durable question"

    assert session.statement is not None
    params = session.statement.compile().params
    event_types = next(value for value in params.values() if isinstance(value, list))
    assert event_types == ["RUN_QUEUED", "USER_QUERY"]


@pytest.mark.asyncio
async def test_load_query_retains_legacy_query_payload_key() -> None:
    session = RecordingSession({"query": "legacy question"})
    store = SqlAlchemyQAGraphStore(cast(AsyncSession, session))

    assert await store.load_query(uuid4()) == "legacy question"
