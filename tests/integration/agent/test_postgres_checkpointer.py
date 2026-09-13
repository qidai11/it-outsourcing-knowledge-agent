from __future__ import annotations

import os

import pytest

from project_agent.agent.checkpoint import async_postgres_saver


@pytest.mark.asyncio
async def test_async_postgres_saver_setup_against_live_postgres() -> None:
    if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL checkpoint gate")
    pytest.importorskip(
        "langgraph.checkpoint.postgres.aio",
        reason="langgraph-checkpoint-postgres is not installed",
    )
    database_url = os.environ["DATABASE_URL"]
    async with async_postgres_saver(database_url) as saver:
        assert saver.__class__.__name__ == "AsyncPostgresSaver"
