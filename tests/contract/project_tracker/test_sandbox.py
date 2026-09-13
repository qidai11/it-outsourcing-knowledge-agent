from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from project_agent.application.ports.project_tracker import SearchIssuesRequest


def test_sandbox_search_statement_is_project_scoped() -> None:
    from project_agent.infrastructure.project_tracker.sandbox import SandboxProjectTrackerAdapter

    project_id = uuid4()
    stmt = SandboxProjectTrackerAdapter.build_search_statement(
        SearchIssuesRequest(
            project_id=str(project_id),
            query="import failed",
            error_code="ERR-IMPORT-004",
            module="import",
            statuses=("OPEN", "IN_PROGRESS"),
            limit=10,
        )
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()

    assert "sandbox_issues.project_id" in sql
    assert project_id.hex in sql.replace("-", "")
    assert "sandbox_issues.error_code" in sql
    assert "sandbox_issues.module" in sql
    assert "sandbox_issues.status" in sql
    assert "sandbox_issues.title" in sql
    assert "sandbox_issues.description" in sql


def test_sandbox_search_rejects_invalid_limit() -> None:
    from project_agent.infrastructure.project_tracker.sandbox import SandboxProjectTrackerAdapter

    with pytest.raises(ValueError, match="limit"):
        SandboxProjectTrackerAdapter.build_search_statement(
            SearchIssuesRequest(project_id=str(uuid4()), limit=0)
        )


def test_project_issue_mapping_keeps_created_at() -> None:
    from project_agent.infrastructure.project_tracker.sandbox import SandboxProjectTrackerAdapter
    from project_agent.infrastructure.db.models.schema import SandboxIssueModel

    created_at = datetime(2026, 8, 8, 1, 2, 3, tzinfo=UTC)
    model = SandboxIssueModel(
        id=uuid4(),
        project_id=uuid4(),
        sandbox_project_id=uuid4(),
        issue_key="ALPHA-101",
        title="Import failed",
        description="encoding root cause",
        issue_type="bug",
        priority="high",
        status="OPEN",
        module="import",
        error_code="ERR-IMPORT-004",
        environment="uat",
        reporter_id=uuid4(),
        source="sandbox",
        created_at=created_at,
        updated_at=created_at,
    )

    issue = SandboxProjectTrackerAdapter.to_project_issue(model)
    assert issue.project_id == str(model.project_id)
    assert issue.issue_key == "ALPHA-101"
    assert issue.created_at == created_at

@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 after applying migrations",
)
async def test_live_sandbox_search_is_strictly_project_scoped() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from project_agent.infrastructure.db.models.schema import (
        ClientModel,
        ProjectModel,
        SandboxIssueModel,
        SandboxProjectModel,
    )
    from project_agent.infrastructure.project_tracker.sandbox import SandboxProjectTrackerAdapter

    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    company_id = uuid4()
    reporter_id = uuid4()
    manager_id = uuid4()
    client = ClientModel(id=uuid4(), company_id=company_id, name="Task12 Client")
    alpha = ProjectModel(
        id=uuid4(), company_id=company_id, client_id=client.id,
        code=f"PRJ-ALPHA-{uuid4().hex[:6].upper()}", name="Alpha", manager_id=manager_id,
    )
    beta = ProjectModel(
        id=uuid4(), company_id=company_id, client_id=client.id,
        code=f"PRJ-BETA-{uuid4().hex[:6].upper()}", name="Beta", manager_id=manager_id,
    )
    alpha_sandbox = SandboxProjectModel(
        id=uuid4(),
        project_id=alpha.id,
        external_key=f"A{uuid4().hex[:8].upper()}",
        name="Alpha Sandbox",
    )
    beta_sandbox = SandboxProjectModel(
        id=uuid4(),
        project_id=beta.id,
        external_key=f"B{uuid4().hex[:8].upper()}",
        name="Beta Sandbox",
    )

    async with session_factory() as session:
        try:
            session.add_all([client, alpha, beta])
            await session.flush()
            session.add_all([alpha_sandbox, beta_sandbox])
            await session.flush()
            session.add_all([
                SandboxIssueModel(
                    id=uuid4(), project_id=alpha.id, sandbox_project_id=alpha_sandbox.id,
                    issue_key="ALPHA-LIVE-1",
                    title="Import failed",
                    description="ERR-IMPORT-004 alpha",
                    issue_type="bug", priority="high", status="OPEN", module="import",
                    error_code="ERR-IMPORT-004", reporter_id=reporter_id, source="sandbox",
                ),
                SandboxIssueModel(
                    id=uuid4(), project_id=beta.id, sandbox_project_id=beta_sandbox.id,
                    issue_key="BETA-LIVE-1",
                    title="Import failed",
                    description="ERR-IMPORT-004 beta",
                    issue_type="bug", priority="high", status="OPEN", module="import",
                    error_code="ERR-IMPORT-004", reporter_id=reporter_id, source="sandbox",
                ),
            ])
            await session.flush()

            adapter = SandboxProjectTrackerAdapter(session)
            rows = await adapter.search_issues(
                SearchIssuesRequest(project_id=str(alpha.id), error_code="ERR-IMPORT-004", limit=20)
            )
            assert [row.issue_key for row in rows] == ["ALPHA-LIVE-1"]
            assert all(row.project_id == str(alpha.id) for row in rows)
        finally:
            await session.rollback()
            await engine.dispose()
