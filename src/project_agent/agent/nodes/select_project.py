from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from project_agent.agent.nodes.analyze_query import QueryAnalysis
from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationService,
)


@dataclass(frozen=True, slots=True)
class ProjectSelection:
    selected_project_id: UUID | None
    candidate_project_codes: tuple[str, ...]
    route: str
    error_code: str | None = None


class ProjectSelectionService:
    def __init__(self, authorization: AuthorizationService) -> None:
        self._authorization = authorization

    async def select(
        self,
        *,
        identity: AuthenticatedIdentity,
        analysis: QueryAnalysis,
        requested_project_id: UUID | None,
    ) -> ProjectSelection:
        memberships = await self._authorization.list_authorized_projects(identity=identity)
        by_id = {item.project_id: item for item in memberships}
        by_code = {item.project_code: item for item in memberships}
        codes = tuple(sorted(by_code))

        query_codes = tuple(dict.fromkeys(analysis.project_codes))

        if requested_project_id is not None:
            requested_membership = by_id.get(requested_project_id)
            if requested_membership is None:
                return ProjectSelection(None, codes, "refusal", "PROJECT_ACCESS_DENIED")
            if query_codes and (
                len(query_codes) != 1 or query_codes[0] != requested_membership.project_code
            ):
                return ProjectSelection(None, codes, "clarification", "PROJECT_MISMATCH")
            return ProjectSelection(requested_project_id, codes, "project_knowledge_qa")

        if len(query_codes) > 1:
            return ProjectSelection(None, codes, "clarification", "AMBIGUOUS_PROJECT")
        if len(query_codes) == 1:
            membership = by_code.get(query_codes[0])
            if membership is None:
                return ProjectSelection(None, codes, "refusal", "PROJECT_ACCESS_DENIED")
            return ProjectSelection(membership.project_id, codes, "project_knowledge_qa")

        if len(memberships) == 1:
            return ProjectSelection(memberships[0].project_id, codes, "project_knowledge_qa")
        if len(memberships) > 1:
            return ProjectSelection(None, codes, "clarification", "PROJECT_REQUIRED")
        return ProjectSelection(None, (), "refusal", "NO_AUTHORIZED_PROJECT")


async def select_project_node(
    state: AgentState,
    *,
    selector: ProjectSelectionService,
    store: QAGraphStorePort,
) -> AgentState:
    run_id = UUID(state["run_id"])
    analysis_payload = await store.load_artifact(UUID(state["query_analysis_id"]))
    analysis = QueryAnalysis.model_validate(analysis_payload)
    requested = UUID(state["project_id"]) if state.get("project_id") else None
    selection = await selector.select(
        identity=AuthenticatedIdentity(user_id=UUID(state["user_id"])),
        analysis=analysis,
        requested_project_id=requested,
    )
    artifact_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_SELECTION",
        payload={
            "selected_project_id": str(selection.selected_project_id)
            if selection.selected_project_id
            else None,
            "candidate_project_codes": list(selection.candidate_project_codes),
            "route": selection.route,
            "error_code": selection.error_code,
        },
    )
    return {
        "project_id": str(selection.selected_project_id) if selection.selected_project_id else None,
        "project_selection_id": str(artifact_id),
        "route": selection.route,
        "last_error_code": selection.error_code,
    }
