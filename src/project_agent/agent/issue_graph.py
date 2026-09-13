from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_agent.agent.nodes.build_issue_draft import build_issue_draft_node
from project_agent.agent.nodes.confirm_issue_create import confirm_issue_create_node
from project_agent.agent.nodes.execute_issue_create import execute_issue_create_node
from project_agent.agent.nodes.search_issues import search_issues_node
from project_agent.agent.state import AgentState
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.issue_candidates import IssueCandidateService
from project_agent.application.services.issue_confirmation import IssueConfirmationService
from project_agent.application.services.issue_creation import IssueCreationService
from project_agent.application.services.issue_drafts import IssueDraftService


@dataclass(frozen=True, slots=True)
class IssueGraphDependencies:
    candidates: IssueCandidateService
    drafts: IssueDraftService
    confirmations: IssueConfirmationService
    creation: IssueCreationService
    store: QAGraphStorePort


def _after_confirmation(state: AgentState) -> str:
    route = state.get("route")
    if route == "execute_issue_create":
        return "execute_issue_create"
    if route == "cancelled":
        return "cancelled"
    return "refusal"


def build_issue_create_graph(
    deps: IssueGraphDependencies,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the Task 13 human-confirmed issue creation workflow.

    This graph assumes the caller is continuing the Task 12 `continue_create`
    action. It refreshes possible duplicates before freezing the draft, then
    pauses with LangGraph `interrupt()` before any write-side tool call.
    """

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("langgraph is required to compile the issue graph") from exc

    builder = StateGraph(AgentState)

    async def search(state: AgentState) -> AgentState:
        return await search_issues_node(state, candidates=deps.candidates, store=deps.store)

    async def build(state: AgentState) -> AgentState:
        return await build_issue_draft_node(state, drafts=deps.drafts, store=deps.store)

    async def confirm(state: AgentState) -> AgentState:
        return await confirm_issue_create_node(state, confirmations=deps.confirmations)

    async def execute(state: AgentState) -> AgentState:
        return await execute_issue_create_node(state, creation=deps.creation, store=deps.store)

    builder.add_node("search_issues", search)
    builder.add_node("build_issue_draft", build)
    builder.add_node("confirm_issue_create", confirm)
    builder.add_node("execute_issue_create", execute)

    builder.add_edge(START, "search_issues")
    builder.add_edge("search_issues", "build_issue_draft")
    builder.add_edge("build_issue_draft", "confirm_issue_create")
    builder.add_conditional_edges(
        "confirm_issue_create",
        _after_confirmation,
        {
            "execute_issue_create": "execute_issue_create",
            "cancelled": END,
            "refusal": END,
        },
    )
    builder.add_edge("execute_issue_create", END)

    return builder.compile() if checkpointer is None else builder.compile(checkpointer=checkpointer)
