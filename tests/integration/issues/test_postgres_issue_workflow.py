from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from project_agent.application.services.issue_confirmation import IssueConfirmationService
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.issues import ConfirmationAction, IssueCandidateLink, IssueDraftCreate
from project_agent.infrastructure.db.models.schema import (
    AgentRunModel,
    ClientModel,
    IssueCandidateModel,
    ProjectModel,
    SandboxIssueModel,
    SandboxProjectModel,
    ThreadModel,
    ToolConfirmationModel,
)
from project_agent.infrastructure.db.repositories.issue_workflow import (
    PostgresIdempotencyStore,
    SqlAlchemyIssueWorkflowRepository,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL issue workflow integration",
)


@pytest.mark.asyncio
async def test_postgres_issue_draft_confirmation_and_idempotency_barrier() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    company_id, client_id, project_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    thread_id, run_id = uuid4(), uuid4()
    sandbox_project_id, existing_issue_id = uuid4(), uuid4()
    now = datetime.now(UTC)

    async with sessions() as session:
        session.add(ClientModel(id=client_id, company_id=company_id, name="Issue Client"))
        await session.flush()
        session.add(
            ProjectModel(
                id=project_id,
                company_id=company_id,
                client_id=client_id,
                code=f"ISSUE-{str(project_id)[:8]}",
                name="Issue Project",
                phase="test",
                manager_id=user_id,
            )
        )
        await session.flush()
        session.add(
            ThreadModel(
                id=thread_id,
                company_id=company_id,
                project_id=project_id,
                user_id=user_id,
                title="Issue workflow test",
            )
        )
        await session.flush()
        session.add(
            AgentRunModel(
                id=run_id,
                thread_id=thread_id,
                company_id=company_id,
                project_id=project_id,
                user_id=user_id,
            )
        )
        session.add(
            SandboxProjectModel(
                id=sandbox_project_id,
                project_id=project_id,
                external_key=f"T{str(project_id)[:6]}",
                name="Issue Sandbox",
            )
        )
        await session.flush()
        session.add(
            SandboxIssueModel(
                id=existing_issue_id,
                project_id=project_id,
                sandbox_project_id=sandbox_project_id,
                issue_key=f"EXIST-{str(existing_issue_id)[:8]}",
                title="Existing import failure",
                description="ERR-IMPORT-004",
                issue_type="bug",
                priority="medium",
                status="OPEN",
                module="import",
                error_code="ERR-IMPORT-004",
                reporter_id=user_id,
            )
        )
        await session.commit()

    async with sessions() as session:
        repo = SqlAlchemyIssueWorkflowRepository(session)
        drafts = IssueDraftService(repo)
        draft = await repo.create_draft(
            IssueDraftCreate(
                run_id=run_id,
                project_id=project_id,
                created_by=user_id,
                title="New import failure",
                description="模块: import ERR-IMPORT-004 failed",
                issue_type="bug",
                proposed_priority="medium",
            )
        )
        await repo.save_candidate_links(
            draft.id,
            (
                IssueCandidateLink(
                    issue_key=f"EXIST-{str(existing_issue_id)[:8]}",
                    rank=1,
                    score=0.91,
                    reasons=("exact_error_code",),
                ),
            ),
        )
        confirmations = IssueConfirmationService(repo, drafts=drafts, clock=lambda: now)
        prompt = await confirmations.prepare(draft.id)
        receipt = await confirmations.record_decision(
            draft_id=draft.id,
            actor_id=user_id,
            action=ConfirmationAction.CONFIRM,
            request_payload_hash=prompt.request_payload_hash,
        )
        await session.commit()
        assert receipt.request_payload_hash == prompt.request_payload_hash

    store = PostgresIdempotencyStore(sessions)
    first, created_first = await store.reserve(
        namespace="sandbox_issue_create",
        request_id=str(draft.id),
        project_id=project_id,
    )
    second, created_second = await store.reserve(
        namespace="sandbox_issue_create",
        request_id=str(draft.id),
        project_id=project_id,
    )
    assert created_first is True
    assert created_second is False
    assert second.id == first.id

    async with sessions() as session:
        candidate_count = (
            await session.execute(
                select(IssueCandidateModel).where(IssueCandidateModel.issue_draft_id == draft.id)
            )
        ).scalars().all()
        confirmation = await session.get(ToolConfirmationModel, receipt.id)
        index_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE tablename='sandbox_issues' "
                    "AND indexname='uq_sandbox_issues_project_request'"
                )
            )
        ).scalar_one_or_none()
        assert len(candidate_count) == 1
        assert confirmation is not None and confirmation.status == "CONFIRMED"
        assert index_exists == 1

        await session.execute(ProjectModel.__table__.delete().where(ProjectModel.id == project_id))
        await session.execute(ClientModel.__table__.delete().where(ClientModel.id == client_id))
        await session.commit()
    await engine.dispose()
