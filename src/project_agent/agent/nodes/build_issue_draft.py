from __future__ import annotations

from uuid import UUID

from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.issue_candidates import IssueCandidateResult
from project_agent.application.services.issue_drafts import IssueDraftService


async def build_issue_draft_node(
    state: AgentState,
    *,
    drafts: IssueDraftService,
    store: QAGraphStorePort,
) -> AgentState:
    if not state.get("project_id"):
        return {"route": "refusal", "last_error_code": "PROJECT_REQUIRED"}
    if not state.get("access_scope_id"):
        return {"route": "refusal", "last_error_code": "PROJECT_SCOPE_REQUIRED"}
    run_id = UUID(state["run_id"])
    text = await store.load_query(run_id)
    candidate_result = None
    candidate_id = state.get("issue_candidate_id")
    if candidate_id:
        candidate_result = IssueCandidateResult.model_validate(
            await store.load_artifact(UUID(candidate_id))
        )
    evidence_ids: tuple[str, ...] = ()
    bundle_id = state.get("evidence_bundle_id")
    if bundle_id:
        frozen = await store.load_governed_evidence_bundle(UUID(bundle_id))
        evidence_ids = tuple(str(item.snapshot_id) for item in frozen.evidence)
    draft = await drafts.create_from_text(
        run_id=run_id,
        project_id=UUID(state["project_id"]),
        created_by=UUID(state["user_id"]),
        text=text,
        candidates=candidate_result,
        evidence_ids=evidence_ids,
    )
    return {
        "issue_draft_id": str(draft.id),
        "route": "confirm_issue_create",
        "last_error_code": None,
    }
