from __future__ import annotations

import os

import pytest
from tests.integration.workers.test_run_worker_postgres import _cleanup, _seed_execute_run

from project_agent.infrastructure.db.models.schema import AgentRunModel
from project_agent.infrastructure.db.repositories.qa_graph import SqlAlchemyQAGraphStore
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.observability.cost import TokenCostPolicy, cost_policy_context
from project_agent.observability.metrics import ObservabilityMetrics, metrics_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run WS6 Run telemetry gate",
)


@pytest.mark.asyncio
async def test_run_cumulative_tokens_cost_and_retrieval_are_durable() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = create_session_factory(engine)
    seeded = await _seed_execute_run(factory)
    metrics = ObservabilityMetrics()
    policy = TokenCostPolicy(333_333, 777_777, "USD")
    try:
        async with factory() as session:
            store = SqlAlchemyQAGraphStore(session)
            with cost_policy_context(policy), metrics_context(metrics):
                await store.record_llm_usage(run_id=seeded.run_id, input_tokens=3, output_tokens=2)
                await store.record_llm_usage(run_id=seeded.run_id, input_tokens=4, output_tokens=1)
                await store.increment_retrieval_rounds(run_id=seeded.run_id)
            await session.commit()

        async with factory() as session:
            run = await session.get(AgentRunModel, seeded.run_id)
            assert run is not None
            assert run.input_tokens == 7
            assert run.output_tokens == 3
            assert run.total_tokens == 10
            assert run.estimated_cost_microunits == (7 * 333_333 + 3 * 777_777) // 1_000_000
            assert run.cost_currency == "USD"
            assert run.retrieval_rounds == 1
        assert 'project_agent_retrieval_rounds_total 1.0' in metrics.render_latest().decode()
    finally:
        await _cleanup(factory, seeded)
        await engine.dispose()
