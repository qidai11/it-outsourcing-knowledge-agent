from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.models import RetrievalPlan
from project_agent.agent.nodes.serialization import deserialize_authorized_context
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.agent.state import AgentState
from project_agent.application.ports.knowledge import (
    KnowledgeRetrievalPort,
    KnowledgeRetrievalRequest,
)
from project_agent.application.ports.qa_graph import QAGraphStorePort


async def retrieve_node(
    state: AgentState,
    *,
    knowledge: KnowledgeRetrievalPort,
    access_policy: ProjectAccessPolicy,
    store: QAGraphStorePort,
) -> AgentState:
    run_id = UUID(state["run_id"])
    context = deserialize_authorized_context(
        await store.load_artifact(UUID(state["access_scope_id"]))
    )
    plan = RetrievalPlan.model_validate(
        await store.load_artifact(UUID(state["retrieval_plan_id"]))
    )
    request = KnowledgeRetrievalRequest(
        project_id=context.project_code,
        query=plan.standalone_query,
        limit=10,
        document_version_ids=tuple(str(value) for value in plan.constrained_document_version_ids),
    )
    constrained = access_policy.constrain_retrieval(request, context)
    chunks = []
    if constrained is not None:
        await store.increment_retrieval_rounds(run_id=run_id)
        chunks = access_policy.postfilter_evidence(await knowledge.retrieve(constrained), context)
    bundle_id = await store.save_evidence_bundle(
        run_id=run_id,
        project_id=UUID(state["project_id"]),
        query_text=plan.original_query,
        chunks=chunks,
    )
    return {
        "evidence_bundle_id": str(bundle_id),
        "route": "answer" if chunks else "refusal",
        "last_error_code": None if chunks else "NO_AUTHORIZED_EVIDENCE",
    }
