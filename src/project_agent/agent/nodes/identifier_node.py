from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.analyze_query import QueryAnalysis
from project_agent.agent.nodes.models import RetrievalPlan
from project_agent.agent.nodes.resolve_identifiers import ExactIdentifierResolver
from project_agent.agent.nodes.serialization import deserialize_authorized_context
from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort


async def resolve_identifiers_node(
    state: AgentState,
    *,
    exact_resolver: ExactIdentifierResolver,
    store: QAGraphStorePort,
) -> AgentState:
    run_id = UUID(state["run_id"])
    analysis = QueryAnalysis.model_validate(
        await store.load_artifact(UUID(state["query_analysis_id"]))
    )
    context = deserialize_authorized_context(
        await store.load_artifact(UUID(state["access_scope_id"]))
    )
    allowed = tuple(context.scope.allowed_document_version_ids or ())
    resolution = await exact_resolver.resolve(
        project_id=UUID(state["project_id"]),
        analysis=analysis,
        allowed_document_version_ids=allowed,
    )
    plan = RetrievalPlan(
        original_query=analysis.original_query,
        standalone_query=analysis.standalone_query,
        exact_identifiers=tuple(item.raw_value for item in analysis.exact_identifiers),
        identifier_resolutions=resolution.resolutions,
        constrained_document_version_ids=resolution.constrained_document_version_ids,
        allowed_categories=tuple(context.scope.allowed_document_categories),
        allow_second_round=False,
    )
    artifact_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=plan.model_dump(mode="json"),
    )
    return {"retrieval_plan_id": str(artifact_id)}
