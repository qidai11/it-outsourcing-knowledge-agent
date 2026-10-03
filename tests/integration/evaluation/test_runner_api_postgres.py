"""WS8 Task 4 live gate: actual Run API, isolated PostgreSQL and Issue services.

A deliberately unstarted worker is NOT a real LLM/RAGFlow acceptance run; these
integration tests prove the API/DB protocol seam and production fault driver.
Only Task 2's newly prepared, disposable evaluation test namespace is touched.
"""
from __future__ import annotations

import os
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from project_agent.evaluation.artifacts import ArtifactStore
from project_agent.evaluation.client import EvaluationClient
from project_agent.evaluation.models import TrialClassification
from project_agent.evaluation.runner import EvaluationRunner, PostgresEvaluationBackend
from project_agent.evaluation.scenarios import PostgresIssueScenarioDriver
from project_agent.infrastructure.db.models.schema import (
    AgentRunModel,
    BackgroundJobModel,
    IdempotencyRecordModel,
    SandboxIssueModel,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="requires RUN_POSTGRES_INTEGRATION=1 and a dedicated WS8_EVAL_DATABASE_URL",
)

# A test-only secret, never persisted or printed, shared only by the in-process
# production FastAPI application and its evaluation API client.
_TEST_JWT_SECRET = token_urlsafe(32)


def _settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    from project_agent.config import Settings

    url = os.environ["WS8_EVAL_DATABASE_URL"]
    name = url.split("?", maxsplit=1)[0].rsplit("/", maxsplit=1)[-1]
    if "eval" not in name.lower() or url == os.getenv("DATABASE_URL"):
        pytest.fail("Task 4 API integration requires an isolated evaluation database")
    return Settings(
        app_env="test",
        database_url=url,
        local_storage_root=tmp_path,
        ragflow_base_url="http://ragflow.invalid",
        ragflow_api_key=SecretStr("test-only-unconnected-ragflow-key"),
        ragflow_expected_version="unconnected-test",
        llm_base_url="http://llm.invalid",
        llm_api_key=SecretStr("test-only-unconnected-llm-key"),
        llm_model_alias="unconnected-test",
        llm_request_capacity=1,
        llm_token_capacity=1000,
        jwt_hs256_secret=SecretStr(_TEST_JWT_SECRET),
        jwt_issuer="project-agent",
        jwt_audience="project-agent-api",
    )


@pytest.mark.asyncio
async def test_runner_authorization_denial_and_frozen_scope_via_production_api(
    prepared_postgres, tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    from project_agent.main import create_app
    from project_agent.runtime.api import build_api_runtime

    dataset, _namespace, sessions, state = prepared_postgres
    settings = _settings(tmp_path)
    app = create_app(settings)
    store = ArtifactStore(tmp_path, f"task4-api-{uuid4().hex}")
    async with build_api_runtime(settings) as runtime:
        app.state.runtime = runtime
        async with EvaluationClient(
            api_base_url="http://eval-api.test",
            fixture_state=state,
            jwt_secret=_TEST_JWT_SECRET,
            transport=httpx.ASGITransport(app=app),
            poll_interval_seconds=0.001,
        ) as client:
            runner = EvaluationRunner(
                dataset, state, store, client, PostgresEvaluationBackend(sessions),
            )
            trials = await runner.run(case_ids=["Q040", "Q014", "Q046", "Q049"])
    assert len(trials) == 4
    assert [trial.case_id for trial in trials] == ["Q014", "Q040", "Q046", "Q049"]
    by_case = {trial.case_id: trial for trial in trials}
    denied = by_case["Q040"]
    assert denied.classification is TrialClassification.SCORED
    assert denied.http_status == 403
    assert denied.run_id is None
    assert all(
        by_case[case_id].classification is TrialClassification.UNSCORABLE_RUNTIME_SCOPE
        for case_id in ("Q014", "Q046", "Q049")
    )
    assert len(list(store.root.glob("cases/*/trial-001.json"))) == 4
    async with sessions() as session:
        assert await session.scalar(select(func.count(AgentRunModel.id)).where(
            AgentRunModel.project_id == UUID(str(state["project_ids"]["PRJ-LOGISTICS-BETA"])),
            AgentRunModel.user_id == UUID(str(state["user_ids"]["u-alpha-dev"])),
        )) == 0

@pytest.mark.asyncio
async def test_runner_fault_protocols_reuse_actual_postgres_issue_services(
    prepared_postgres, tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    """No worker is launched: Q044/Q045 use the frozen controlled service path."""
    from project_agent.main import create_app
    from project_agent.runtime.api import build_api_runtime

    dataset, _namespace, sessions, state = prepared_postgres
    settings = _settings(tmp_path)
    app = create_app(settings)
    run_id = f"task4-issue-{uuid4().hex}"
    store = ArtifactStore(tmp_path, run_id)
    driver = PostgresIssueScenarioDriver(
        dataset_root=dataset.root,
        evaluation_namespace=f"{state['evaluation_namespace']}/{run_id}",
        fixture_state=state,
        session_factory=sessions,
    )
    expected_requests = {
        case_id: driver.request_id(next(case for case in dataset.cases
                                        if case.case_id == case_id))
        for case_id in ("Q044", "Q045")
    }
    run_ids: tuple[UUID, ...] = ()
    try:
        async with build_api_runtime(settings) as runtime:
            app.state.runtime = runtime
            async with EvaluationClient(
                api_base_url="http://eval-api.test",
                fixture_state=state,
                jwt_secret=_TEST_JWT_SECRET,
                transport=httpx.ASGITransport(app=app),
                poll_interval_seconds=0.001,
            ) as client:
                runner = EvaluationRunner(
                    dataset, state, store, client, PostgresEvaluationBackend(sessions),
                    scenario_driver=driver,
                )
                trials = await runner.run(case_ids=["Q044", "Q045"])
        run_ids = tuple(UUID(t.run_id) for t in trials if t.run_id)
        assert len(trials) == 2
        assert all(t.classification is TrialClassification.SCORED for t in trials)
        assert trials[0].metadata["observed_creation_outcome"] == "ALREADY_CREATED"
        assert trials[1].metadata["observed_creation_outcome"] == "RECONCILED"
        assert len(run_ids) == 2
        project = UUID(str(state["project_ids"]["PRJ-RETAIL-ALPHA"]))
        async with sessions() as session:
            for request_id in expected_requests.values():
                assert await session.scalar(select(func.count(SandboxIssueModel.id)).where(
                    SandboxIssueModel.project_id == project,
                    SandboxIssueModel.client_request_id == request_id,
                )) == 1
                record = await session.scalar(select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.namespace == "sandbox_issue_create",
                    IdempotencyRecordModel.request_id == request_id,
                ))
                assert record is not None and record.status == "COMPLETED"
    finally:
        # If a trial failed after creating a Run, artifacts can still expose its
        # trace; additionally locate jobs only in this disposable test namespace.
        async with sessions() as session:
            rows = (await session.scalars(select(AgentRunModel.id).where(
                AgentRunModel.project_id == UUID(str(state["project_ids"]["PRJ-RETAIL-ALPHA"])),
            ))).all()
            from project_agent.evaluation.scenarios import fixed_request_uuid

            draft_ids = tuple(str(fixed_request_uuid(
                f"{state['evaluation_namespace']}/{run_id}", case,
                "eval-v0-{case_id}-alpha-confirmed-create",
            )) for case in ("Q044", "Q045"))
            jobs = tuple(str(item) for item in rows) + draft_ids
            if jobs:
                await session.execute(delete(BackgroundJobModel).where(
                    BackgroundJobModel.aggregate_id.in_(jobs),
                ))
                await session.commit()
