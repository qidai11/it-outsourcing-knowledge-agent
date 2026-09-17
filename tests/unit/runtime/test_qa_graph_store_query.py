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


class ArtifactSession:
    def __init__(self, *, event: object | None = None) -> None:
        self.event = event
        self.added: list[object] = []
        self.flush_calls = 0

    def add(self, row: object) -> None:
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid4()

    async def flush(self) -> None:
        self.flush_calls += 1

    async def get(self, _model: object, _key: object) -> object | None:
        return self.event


@pytest.mark.asyncio
async def test_save_artifact_uses_stable_artifact_available_event_envelope(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from project_agent.domain.runs import AgentEventType
    from project_agent.infrastructure.db.models.schema import AgentEventModel

    session = ArtifactSession()
    store = SqlAlchemyQAGraphStore(cast(AsyncSession, session))
    monkeypatch.setattr(store, "_next_sequence", AsyncMock(return_value=4))
    run_id = uuid4()

    artifact_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROMPT_SNAPSHOT",
        payload={"version": 7, "content_hash": "abc123"},
    )

    assert len(session.added) == 1
    row = cast(AgentEventModel, session.added[0])
    assert artifact_id == row.id
    assert row.run_id == run_id
    assert row.sequence_no == 4
    assert row.event_type == AgentEventType.ARTIFACT_AVAILABLE.value
    assert row.payload_json == {
        "artifact_type": "PROMPT_SNAPSHOT",
        "artifact": {"version": 7, "content_hash": "abc123"},
    }
    assert session.flush_calls == 1


@pytest.mark.asyncio
async def test_load_artifact_unwraps_artifact_available_event_envelope() -> None:
    from project_agent.domain.runs import AgentEventType
    from project_agent.infrastructure.db.models.schema import AgentEventModel

    artifact_id = uuid4()
    event = AgentEventModel(
        id=artifact_id,
        run_id=uuid4(),
        sequence_no=3,
        event_type=AgentEventType.ARTIFACT_AVAILABLE.value,
        payload_json={
            "artifact_type": "RETRIEVAL_PLAN",
            "artifact": {"standalone_query": "approved design"},
        },
    )
    session = ArtifactSession(event=event)
    store = SqlAlchemyQAGraphStore(cast(AsyncSession, session))

    assert await store.load_artifact(artifact_id) == {
        "standalone_query": "approved design"
    }
