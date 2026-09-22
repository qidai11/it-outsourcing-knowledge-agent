from __future__ import annotations

from uuid import uuid4

import pytest
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.analyze_query import QueryAnalysis
from project_agent.agent.nodes.identifier_node import resolve_identifiers_node
from project_agent.agent.nodes.models import RetrievalPlan
from project_agent.agent.nodes.resolve_identifiers import ExactResolutionResult
from project_agent.agent.nodes.serialization import serialize_authorized_context
from project_agent.application.services.authorization import AuthorizedProjectContext
from project_agent.domain.access import ProjectAccessScope


class _EmptyExactResolver:
    async def resolve(self, **kwargs: object) -> ExactResolutionResult:
        return ExactResolutionResult(resolutions=(), constrained_document_version_ids=())


@pytest.mark.asyncio
async def test_identifier_resolution_enables_one_bounded_second_round() -> None:
    run_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    store = InMemoryQAGraphStore()
    analysis_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="QUERY_ANALYSIS",
        payload=QueryAnalysis(
            original_query="rollback ALPHA",
            standalone_query="rollback ALPHA",
            exact_identifiers=(),
        ).model_dump(mode="json"),
    )
    context = AuthorizedProjectContext(
        scope=ProjectAccessScope(
            company_id=uuid4(),
            user_id=user_id,
            allowed_client_ids=(uuid4(),),
            allowed_project_ids=(project_id,),
            allowed_document_version_ids=(uuid4(),),
            allowed_document_categories=("runbook",),
            role_ids=("developer",),
            policy_version="test",
        ),
        project_code="PRJ-ALPHA",
        knowledge_space_ids=("dataset-alpha",),
    )
    scope_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )

    result = await resolve_identifiers_node(
        {
            "run_id": str(run_id),
            "project_id": str(project_id),
            "query_analysis_id": str(analysis_id),
            "access_scope_id": str(scope_id),
        },
        exact_resolver=_EmptyExactResolver(),  # type: ignore[arg-type]
        store=store,
    )
    plan = RetrievalPlan.model_validate(
        await store.load_artifact(__import__("uuid").UUID(result["retrieval_plan_id"]))
    )

    assert plan.allow_second_round is True
