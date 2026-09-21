from __future__ import annotations

import os
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from tests.live.conftest import make_live_token, wait_for_run_status

from project_agent.infrastructure.db.models.schema import (
    AnswerModel,
    CitationModel,
    EvidenceBundleModel,
    EvidenceSnapshotModel,
)
from project_agent.infrastructure.db.session import create_engine, create_session_factory


def _headers(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_live_token(user_id=user_id)}"}


def _api_base() -> str:
    return os.getenv("WS7_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@pytest.mark.asyncio
async def test_compose_qa_run_crosses_api_worker_and_persists_authorized_evidence(
    ws7_live_scope,
) -> None:  # type: ignore[no-untyped-def]
    scope, marker = ws7_live_scope
    headers = _headers(scope.user_a)
    async with httpx.AsyncClient(base_url=_api_base(), timeout=120.0) as client:
        response = await client.post(
            "/api/v1/runs",
            json={
                "project_id": str(scope.project_a),
                "business_mode": "qa",
                "query": f"What exact approved WS7 acceptance marker is required? {marker}",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["status"] == "QUEUED"
        run_id = UUID(created["run_id"])

        final = await wait_for_run_status(
            client,
            run_id=run_id,
            headers=headers,
            expected={"SUCCEEDED"},
            timeout_seconds=120.0,
        )
        assert final["status"] == "SUCCEEDED"
        events = await client.get(f"/api/v1/runs/{run_id}/events", headers=headers)
        assert events.status_code == 200, events.text
        assert "event: RUN_SUCCEEDED" in events.text

    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            answer = await session.scalar(select(AnswerModel).where(AnswerModel.run_id == run_id))
            bundle_ids = select(EvidenceBundleModel.id).where(
                EvidenceBundleModel.run_id == run_id
            )
            assert answer is not None
            evidence = (
                await session.scalars(
                    select(EvidenceSnapshotModel).where(
                        EvidenceSnapshotModel.bundle_id.in_(bundle_ids)
                    )
                )
            ).all()
            citations = (
                await session.scalars(
                    select(CitationModel).where(CitationModel.answer_id == answer.id)
                )
            ).all()
        assert evidence
        assert citations
        assert all(item.project_id == scope.project_a for item in evidence)
        assert any(marker in item.content for item in evidence)
        evidence_ids = {item.id for item in evidence}
        assert all(item.evidence_snapshot_id in evidence_ids for item in citations)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_compose_qa_run_is_not_readable_by_non_member(
    ws7_live_scope,
) -> None:  # type: ignore[no-untyped-def]
    scope, marker = ws7_live_scope
    owner_headers = _headers(scope.user_a)
    outsider_headers = _headers(scope.user_b)
    async with httpx.AsyncClient(base_url=_api_base(), timeout=120.0) as client:
        created = await client.post(
            "/api/v1/runs",
            json={
                "project_id": str(scope.project_a),
                "business_mode": "qa",
                "query": f"Read the authorized acceptance marker {marker}",
            },
            headers=owner_headers,
        )
        assert created.status_code == 201, created.text
        run_id = UUID(created.json()["run_id"])

        forbidden_run = await client.get(f"/api/v1/runs/{run_id}", headers=outsider_headers)
        assert forbidden_run.status_code == 403
        forbidden_events = await client.get(
            f"/api/v1/runs/{run_id}/events",
            headers=outsider_headers,
        )
        assert forbidden_events.status_code == 403

        await wait_for_run_status(
            client,
            run_id=run_id,
            headers=owner_headers,
            expected={"SUCCEEDED"},
            timeout_seconds=120.0,
        )
