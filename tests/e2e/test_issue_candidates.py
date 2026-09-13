from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from project_agent.agent.nodes.search_issues import search_issues_node
from project_agent.agent.nodes.serialization import serialize_authorized_context
from project_agent.agent.state import AgentState
from project_agent.application.services.authorization import AuthorizedProjectContext
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.application.services.issue_candidates import (
    IssueCandidateAction,
    IssueCandidateQuery,
    IssueCandidateService,
)
from project_agent.domain.access import ProjectAccessScope
from tests.fakes.project_tracker import SandboxProjectTrackerAdapter
from tests.fakes.qa_graph_store import InMemoryQAGraphStore


@pytest.fixture
def candidate_fixture():
    now = datetime(2026, 8, 8, tzinfo=UTC)
    alpha = str(uuid4())
    beta = str(uuid4())
    tracker = SandboxProjectTrackerAdapter()

    tracker.seed_issue(
        project_id=alpha,
        issue_key="ALPHA-101",
        title="CSV import fails with invalid encoding",
        description="Upload returns ERR-IMPORT-004 because the CSV encoding is invalid.",
        status="OPEN",
        module="import",
        error_code="ERR-IMPORT-004",
        priority="high",
        created_at=now - timedelta(hours=1),
    )
    tracker.seed_issue(
        project_id=alpha,
        issue_key="ALPHA-102",
        title="CSV import fails after gateway timeout",
        description=(
            "Same ERR-IMPORT-004 is surfaced, but root cause is an upstream gateway timeout."
        ),
        status="RESOLVED",
        module="import",
        error_code="ERR-IMPORT-004",
        priority="medium",
        created_at=now - timedelta(days=2),
    )
    tracker.seed_issue(
        project_id=alpha,
        issue_key="ALPHA-103",
        title="CSV import fails with invalid encoding",
        description="The parser returns a different validation error.",
        status="OPEN",
        module="import",
        error_code="ERR-IMPORT-005",
        created_at=now - timedelta(minutes=20),
    )
    tracker.seed_issue(
        project_id=beta,
        issue_key="BETA-201",
        title="CSV import fails with invalid encoding",
        description="Beta has the same text and same error code but a different root cause.",
        status="OPEN",
        module="import",
        error_code="ERR-IMPORT-004",
        created_at=now,
    )
    service = IssueCandidateService(tracker=tracker, extractor=IdentifierExtractor())
    return tracker, service, alpha, beta


@pytest.mark.asyncio
async def test_possible_duplicates_are_ranked_and_never_cross_projects(candidate_fixture) -> None:
    tracker, service, alpha, _ = candidate_fixture
    result = await service.find_candidates(
        IssueCandidateQuery(
            project_id=alpha,
            title="CSV import fails with invalid encoding",
            description="UAT upload failed with ERR-IMPORT-004 in import module.",
            error_code="ERR-IMPORT-004",
            module="import",
            limit=5,
        )
    )

    assert [item.issue_key for item in result.possible_duplicates][:2] == [
        "ALPHA-101",
        "ALPHA-102",
    ]
    assert all(item.project_id == alpha for item in result.possible_duplicates)
    assert "exact_error_code" in result.possible_duplicates[0].reasons
    assert "module_match" in result.possible_duplicates[0].reasons
    assert result.user_options == (
        IssueCandidateAction.VIEW_EXISTING,
        IssueCandidateAction.LINK_EXISTING,
        IssueCandidateAction.CONTINUE_CREATE,
        IssueCandidateAction.CANCEL,
    )
    assert not hasattr(result, "duplicate")
    assert all(not hasattr(item, "duplicate") for item in result.possible_duplicates)
    assert tracker.create_side_effect_count == 0


@pytest.mark.asyncio
async def test_optional_semantic_score_cannot_override_exact_error_code(candidate_fixture) -> None:
    _, service, alpha, _ = candidate_fixture
    result = await service.find_candidates(
        IssueCandidateQuery(
            project_id=alpha,
            title="CSV import fails with invalid encoding",
            description="import failed",
            error_code="ERR-IMPORT-004",
            module="import",
            semantic_scores={"ALPHA-103": 1.0, "ALPHA-101": 0.0},
            limit=5,
        )
    )

    assert result.possible_duplicates[0].issue_key == "ALPHA-101"
    assert result.possible_duplicates[0].score > next(
        item.score for item in result.possible_duplicates if item.issue_key == "ALPHA-103"
    )


@pytest.mark.asyncio
async def test_from_text_extracts_error_code_and_module(candidate_fixture) -> None:
    _, service, alpha, _ = candidate_fixture
    result = await service.find_candidates_from_text(
        project_id=alpha,
        text="模块: import；UAT CSV import fails with ERR-IMPORT-004 invalid encoding",
        limit=3,
    )

    assert result.query.error_code == "ERR-IMPORT-004"
    assert result.query.module == "import"
    assert result.possible_duplicates[0].issue_key == "ALPHA-101"


@pytest.mark.asyncio
async def test_search_issue_node_persists_candidates_as_artifact(candidate_fixture) -> None:
    tracker, service, alpha, _ = candidate_fixture
    store = InMemoryQAGraphStore()
    run_id = uuid4()
    store.seed_query(
        run_id, "模块: import，CSV import fails with ERR-IMPORT-004 invalid encoding"
    )
    user_id = uuid4()
    alpha_uuid = __import__("uuid").UUID(alpha)
    scope_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="ACCESS_SCOPE",
        payload=serialize_authorized_context(
            AuthorizedProjectContext(
                scope=ProjectAccessScope(
                    company_id=uuid4(),
                    user_id=user_id,
                    allowed_client_ids=(uuid4(),),
                    allowed_project_ids=(alpha_uuid,),
                    allowed_document_version_ids=(),
                    role_ids=("developer",),
                    policy_version="project-membership-v1",
                ),
                project_code="PRJ-RETAIL-ALPHA",
                knowledge_space_ids=(),
            )
        ),
    )
    state: AgentState = {
        "run_id": str(run_id),
        "thread_id": str(uuid4()),
        "user_id": str(user_id),
        "project_id": alpha,
        "access_scope_id": str(scope_id),
    }

    result = await search_issues_node(state, candidates=service, store=store)
    payload = await store.load_artifact(__import__("uuid").UUID(result["issue_candidate_id"]))

    assert result["route"] == "issue_candidates"
    assert payload["possible_duplicates"][0]["issue_key"] == "ALPHA-101"
    assert "duplicate" not in payload
    assert tracker.create_side_effect_count == 0


@pytest.mark.asyncio
async def test_search_issue_node_requires_authorized_scope(candidate_fixture) -> None:
    tracker, service, alpha, _ = candidate_fixture
    store = InMemoryQAGraphStore()
    run_id = uuid4()
    store.seed_query(run_id, "ERR-IMPORT-004")
    result = await search_issues_node(
        {
            "run_id": str(run_id),
            "thread_id": str(uuid4()),
            "user_id": str(uuid4()),
            "project_id": alpha,
        },
        candidates=service,
        store=store,
    )
    assert result["route"] == "refusal"
    assert result["last_error_code"] == "PROJECT_SCOPE_REQUIRED"
    assert tracker.search_requests == []
