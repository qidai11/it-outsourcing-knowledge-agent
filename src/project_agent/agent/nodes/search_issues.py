from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.serialization import deserialize_authorized_context
from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.issue_candidates import IssueCandidateService


async def search_issues_node(
    state: AgentState,
    *,
    candidates: IssueCandidateService,
    store: QAGraphStorePort,
) -> AgentState:
    project_id = state.get("project_id")
    access_scope_id = state.get("access_scope_id")
    if not project_id:
        return {"route": "clarification", "last_error_code": "PROJECT_REQUIRED"}
    if not access_scope_id:
        return {"route": "refusal", "last_error_code": "PROJECT_SCOPE_REQUIRED"}

    context = deserialize_authorized_context(await store.load_artifact(UUID(access_scope_id)))
    try:
        project_uuid = UUID(project_id)
    except ValueError:
        return {"route": "refusal", "last_error_code": "INVALID_PROJECT_ID"}
    if project_uuid not in context.scope.allowed_project_ids:
        return {"route": "refusal", "last_error_code": "PROJECT_ACCESS_DENIED"}

    run_id = UUID(state["run_id"])
    query_text = await store.load_query(run_id)
    result = await candidates.find_candidates_from_text(
        project_id=project_id,
        text=query_text,
    )
    artifact_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="ISSUE_CANDIDATES",
        payload=result.model_dump(mode="json"),
    )
    return {
        "issue_candidate_id": str(artifact_id),
        "route": "issue_candidates",
        "last_error_code": None,
    }
