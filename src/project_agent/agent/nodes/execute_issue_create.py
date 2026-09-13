from __future__ import annotations

from uuid import UUID

from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.issue_creation import (
    IssueCreationDenied,
    IssueCreationService,
    IssueCreationStatus,
)


async def execute_issue_create_node(
    state: AgentState,
    *,
    creation: IssueCreationService,
    store: QAGraphStorePort,
) -> AgentState:
    draft_id = state.get("issue_draft_id")
    confirmation_id = state.get("tool_confirmation_id")
    if not draft_id or not confirmation_id:
        return {"route": "refusal", "last_error_code": "CONFIRMATION_REQUIRED"}
    try:
        outcome = await creation.execute(
            draft_id=UUID(draft_id),
            confirmation_id=UUID(confirmation_id),
            actor_id=UUID(state["user_id"]),
        )
    except IssueCreationDenied as exc:
        return {"route": "refusal", "last_error_code": type(exc).__name__}
    artifact_id = await store.save_artifact(
        run_id=UUID(state["run_id"]),
        artifact_type="ISSUE_CREATE_RESULT",
        payload=outcome.model_dump(mode="json"),
    )
    return {
        "issue_creation_id": str(artifact_id),
        "route": (
            "issue_create_pending"
            if outcome.status is IssueCreationStatus.PENDING_RECONCILIATION
            else "issue_created"
        ),
        "last_error_code": None,
    }
