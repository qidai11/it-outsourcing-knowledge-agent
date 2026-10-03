from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from project_agent.evaluation.dataset import load_evaluation_dataset
from project_agent.infrastructure.db.models.schema import ProjectMembershipModel, SandboxIssueModel
from project_agent.infrastructure.db.session import create_session_factory

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 and WS8_EVAL_DATABASE_URL for a dedicated eval DB",
)


def _evaluation_url() -> str:
    url = os.environ["WS8_EVAL_DATABASE_URL"]
    db_name = url.rsplit("/", maxsplit=1)[-1].split("?", maxsplit=1)[0]
    if "eval" not in db_name.lower():
        pytest.fail("WS8_EVAL_DATABASE_URL must name a dedicated evaluation database")
    if url == os.getenv("DATABASE_URL"):
        pytest.fail("WS8_EVAL_DATABASE_URL must not be the primary DATABASE_URL")
    return url


@pytest.mark.asyncio
async def test_cleanup_of_second_namespace_preserves_first_namespace_children() -> None:
    from project_agent.evaluation.fixtures import cleanup_v0, prepare_v0

    engine = create_async_engine(_evaluation_url(), pool_pre_ping=True)
    sessions = create_session_factory(engine)
    dataset = load_evaluation_dataset(DATASET_ROOT)
    namespace_a = f"ws8-v0-isolation-a-{uuid4().hex}"
    namespace_b = f"ws8-v0-isolation-b-{uuid4().hex}"
    state_a = None
    state_b = None
    try:
        state_a = await prepare_v0(
            dataset=dataset,
            evaluation_namespace=namespace_a,
            session_factory=sessions,
            ragflow_adapter=None,
        )
        state_b = await prepare_v0(
            dataset=dataset,
            evaluation_namespace=namespace_b,
            session_factory=sessions,
            ragflow_adapter=None,
        )

        assert set(map(str, state_a["membership_ids"].values())).isdisjoint(
            map(str, state_b["membership_ids"].values())
        )
        assert set(map(str, state_a["sandbox_issue_ids"].values())).isdisjoint(
            map(str, state_b["sandbox_issue_ids"].values())
        )

        await cleanup_v0(
            evaluation_namespace=namespace_b,
            session_factory=sessions,
            ragflow_adapter=None,
        )

        async with sessions() as session:
            for row_id in state_a["membership_ids"].values():
                assert await session.get(ProjectMembershipModel, UUID(str(row_id))) is not None
            for row_id in state_a["sandbox_issue_ids"].values():
                assert await session.get(SandboxIssueModel, UUID(str(row_id))) is not None
            for row_id in state_b["membership_ids"].values():
                assert await session.get(ProjectMembershipModel, UUID(str(row_id))) is None
            for row_id in state_b["sandbox_issue_ids"].values():
                assert await session.get(SandboxIssueModel, UUID(str(row_id))) is None
    finally:
        for namespace in (namespace_b, namespace_a):
            with suppress(Exception):
                await cleanup_v0(
                    evaluation_namespace=namespace,
                    session_factory=sessions,
                    ragflow_adapter=None,
                )
        await engine.dispose()
