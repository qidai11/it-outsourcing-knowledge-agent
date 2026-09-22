from __future__ import annotations

from uuid import UUID

from project_agent.agent.nodes.serialization import serialize_authorized_context
from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationService,
)


async def resolve_scope_node(
    state: AgentState,
    *,
    authorization: AuthorizationService,
    store: QAGraphStorePort,
) -> AgentState:
    if not state.get("project_id"):
        raise ValueError("project_id is required before scope resolution")
    run_id = UUID(state["run_id"])
    context = await authorization.authorize_identity(
        identity=AuthenticatedIdentity(user_id=UUID(state["user_id"])),
        project_id=UUID(state["project_id"]),
    )
    artifact_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )
    return {"access_scope_id": str(artifact_id)}
