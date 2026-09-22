from __future__ import annotations

import json
import os
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from tests.live.conftest import make_live_token, wait_for_run_status

from project_agent.infrastructure.db.models.schema import (
    IdempotencyRecordModel,
    IssueDraftModel,
    SandboxIssueModel,
)
from project_agent.infrastructure.db.session import create_engine, create_session_factory

QUERY = "模块: import ERR-IMPORT-004 failed during acceptance"


def _headers(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_live_token(user_id=user_id)}"}


def _api_base() -> str:
    return os.getenv("WS7_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


async def _waiting_payload_from_sse(
    client: httpx.AsyncClient,
    *,
    run_id: UUID,
    headers: dict[str, str],
) -> dict[str, object]:
    current_event = ""
    async with client.stream(
        "GET",
        f"/api/v1/runs/{run_id}/events",
        headers=headers,
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                current_event = line.removeprefix("event: ")
                continue
            if current_event == "WAITING_CONFIRMATION" and line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
                assert isinstance(payload, dict)
                return payload
    pytest.fail("WAITING_CONFIRMATION SSE event was not observed")


async def _draft_id(run_id: UUID) -> UUID:
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            draft = await session.scalar(
                select(IssueDraftModel).where(IssueDraftModel.run_id == run_id)
            )
            assert draft is not None
            return draft.id
    finally:
        await engine.dispose()


async def _created_issue_count(project_id: UUID, draft_id: UUID) -> int:
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            value = await session.scalar(
                select(func.count())
                .select_from(SandboxIssueModel)
                .where(
                    SandboxIssueModel.project_id == project_id,
                    SandboxIssueModel.client_request_id == str(draft_id),
                )
            )
        return int(value or 0)
    finally:
        await engine.dispose()


async def _assert_completed_idempotency(project_id: UUID, draft_id: UUID) -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            records = (
                await session.scalars(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.namespace == "sandbox_issue_create",
                        IdempotencyRecordModel.request_id == str(draft_id),
                        IdempotencyRecordModel.project_id == project_id,
                    )
                )
            ).all()
        assert len(records) == 1
        assert records[0].status == "COMPLETED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compose_issue_create_interrupt_resume_creates_exactly_one_issue(
    ws7_live_issue_scope,
) -> None:  # type: ignore[no-untyped-def]
    scope, _requirement_version_id = ws7_live_issue_scope
    headers = _headers(scope.user_a)
    async with httpx.AsyncClient(base_url=_api_base(), timeout=120.0) as client:
        response = await client.post(
            "/api/v1/runs",
            json={
                "project_id": str(scope.project_a),
                "business_mode": "issue_create",
                "query": QUERY,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "QUEUED"
        run_id = UUID(response.json()["run_id"])

        waiting = await wait_for_run_status(
            client,
            run_id=run_id,
            headers=headers,
            expected={"WAITING_CONFIRMATION"},
            timeout_seconds=120.0,
        )
        assert waiting["status"] == "WAITING_CONFIRMATION"
        waiting_event = await _waiting_payload_from_sse(
            client,
            run_id=run_id,
            headers=headers,
        )
        request_hash = str(waiting_event.get("request_payload_hash", ""))
        assert len(request_hash) == 64
        assert waiting_event.get("evidence_ids")
        draft_id = await _draft_id(run_id)
        assert await _created_issue_count(scope.project_a, draft_id) == 0

        resumed = await client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"action": "confirm", "request_payload_hash": request_hash},
            headers=headers,
        )
        assert resumed.status_code == 202, resumed.text

        final = await wait_for_run_status(
            client,
            run_id=run_id,
            headers=headers,
            expected={"SUCCEEDED"},
            timeout_seconds=120.0,
        )
        assert final["status"] == "SUCCEEDED"
        assert await _created_issue_count(scope.project_a, draft_id) == 1
        await _assert_completed_idempotency(scope.project_a, draft_id)

        replay = await client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"action": "confirm", "request_payload_hash": request_hash},
            headers=headers,
        )
        assert replay.status_code == 409, replay.text
        assert await _created_issue_count(scope.project_a, draft_id) == 1

        events = await client.get(f"/api/v1/runs/{run_id}/events", headers=headers)
        assert events.status_code == 200, events.text
        assert "event: RUN_SUCCEEDED" in events.text


@pytest.mark.asyncio
async def test_compose_issue_run_is_not_resumable_by_non_member(
    ws7_live_issue_scope,
) -> None:  # type: ignore[no-untyped-def]
    scope, _requirement_version_id = ws7_live_issue_scope
    owner_headers = _headers(scope.user_a)
    outsider_headers = _headers(scope.user_b)
    async with httpx.AsyncClient(base_url=_api_base(), timeout=120.0) as client:
        response = await client.post(
            "/api/v1/runs",
            json={
                "project_id": str(scope.project_a),
                "business_mode": "issue_create",
                "query": QUERY,
            },
            headers=owner_headers,
        )
        assert response.status_code == 201, response.text
        run_id = UUID(response.json()["run_id"])
        await wait_for_run_status(
            client,
            run_id=run_id,
            headers=owner_headers,
            expected={"WAITING_CONFIRMATION"},
            timeout_seconds=120.0,
        )
        waiting_event = await _waiting_payload_from_sse(
            client,
            run_id=run_id,
            headers=owner_headers,
        )
        request_hash = str(waiting_event.get("request_payload_hash", ""))
        assert len(request_hash) == 64
        draft_id = await _draft_id(run_id)
        assert await _created_issue_count(scope.project_a, draft_id) == 0

        forbidden = await client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"action": "confirm", "request_payload_hash": request_hash},
            headers=outsider_headers,
        )
        assert forbidden.status_code == 403, forbidden.text
        assert await _created_issue_count(scope.project_a, draft_id) == 0

        authorized = await client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"action": "confirm", "request_payload_hash": request_hash},
            headers=owner_headers,
        )
        assert authorized.status_code == 202, authorized.text
        await wait_for_run_status(
            client,
            run_id=run_id,
            headers=owner_headers,
            expected={"SUCCEEDED"},
            timeout_seconds=120.0,
        )
