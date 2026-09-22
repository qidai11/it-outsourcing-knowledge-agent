from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_agent.agent.nodes.build_issue_draft import build_issue_draft_node
from project_agent.agent.nodes.confirm_issue_create import confirm_issue_create_node
from project_agent.agent.nodes.execute_issue_create import execute_issue_create_node
from project_agent.agent.nodes.issue_evidence import retrieve_issue_evidence_node
from project_agent.agent.nodes.resolve_scope import resolve_scope_node
from project_agent.agent.nodes.search_issues import search_issues_node
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.agent.state import AgentState
from project_agent.application.ports.knowledge import KnowledgeRetrievalPort
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.evidence_governance import EvidenceGovernanceService
from project_agent.application.services.issue_candidates import IssueCandidateService
from project_agent.application.services.issue_confirmation import IssueConfirmationService
from project_agent.application.services.issue_creation import IssueCreationService
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.application.services.issue_evidence import IssueEvidenceSelector


@dataclass(frozen=True, slots=True)
class IssueLookupRunGraphDependencies:
    authorization: AuthorizationService
    candidates: IssueCandidateService
    store: QAGraphStorePort


def build_issue_lookup_run_graph(
    deps: IssueLookupRunGraphDependencies,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the authorized, read-only issue lookup Run graph."""

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - synchronized runtime dependency
        raise RuntimeError("langgraph is required to compile the issue Run graph") from exc

    builder = StateGraph(AgentState)

    async def scope(state: AgentState) -> AgentState:
        return await resolve_scope_node(
            state,
            authorization=deps.authorization,
            store=deps.store,
        )

    async def search(state: AgentState) -> AgentState:
        return await search_issues_node(
            state,
            candidates=deps.candidates,
            store=deps.store,
        )

    builder.add_node("resolve_scope", scope)
    builder.add_node("search_issues", search)
    builder.add_edge(START, "resolve_scope")
    builder.add_edge("resolve_scope", "search_issues")
    builder.add_edge("search_issues", END)

    if checkpointer is None:
        return builder.compile()
    return builder.compile(checkpointer=checkpointer)


@dataclass(frozen=True, slots=True)
class IssueCreateRunGraphDependencies:
    authorization: AuthorizationService
    evidence_selector: IssueEvidenceSelector
    knowledge: KnowledgeRetrievalPort
    access_policy: ProjectAccessPolicy
    evidence_governance: EvidenceGovernanceService
    candidates: IssueCandidateService
    drafts: IssueDraftService
    confirmations: IssueConfirmationService
    creation: IssueCreationService
    store: QAGraphStorePort


def _after_issue_evidence(state: AgentState) -> str:
    return "search_issues" if state.get("route") == "issue_evidence_ready" else "refusal"


def _after_confirmation(state: AgentState) -> str:
    route = state.get("route")
    if route == "execute_issue_create":
        return "execute_issue_create"
    if route == "cancelled":
        return "cancelled"
    return "refusal"


def build_issue_create_run_graph(
    deps: IssueCreateRunGraphDependencies,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the WS5 evidence-gated, human-confirmed issue-create Run graph."""

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - synchronized runtime dependency
        raise RuntimeError("langgraph is required to compile the issue Run graph") from exc

    builder = StateGraph(AgentState)

    async def scope(state: AgentState) -> AgentState:
        return await resolve_scope_node(
            state,
            authorization=deps.authorization,
            store=deps.store,
        )

    async def evidence(state: AgentState) -> AgentState:
        return await retrieve_issue_evidence_node(
            state,
            selector=deps.evidence_selector,
            knowledge=deps.knowledge,
            access_policy=deps.access_policy,
            evidence_governance=deps.evidence_governance,
            store=deps.store,
        )

    async def search(state: AgentState) -> AgentState:
        return await search_issues_node(
            state,
            candidates=deps.candidates,
            store=deps.store,
        )

    async def build(state: AgentState) -> AgentState:
        return await build_issue_draft_node(
            state,
            drafts=deps.drafts,
            store=deps.store,
        )

    async def confirm(state: AgentState) -> AgentState:
        return await confirm_issue_create_node(
            state,
            confirmations=deps.confirmations,
        )

    async def execute(state: AgentState) -> AgentState:
        return await execute_issue_create_node(
            state,
            creation=deps.creation,
            store=deps.store,
        )

    builder.add_node("resolve_scope", scope)
    builder.add_node("retrieve_issue_evidence", evidence)
    builder.add_node("search_issues", search)
    builder.add_node("build_issue_draft", build)
    builder.add_node("confirm_issue_create", confirm)
    builder.add_node("execute_issue_create", execute)

    builder.add_edge(START, "resolve_scope")
    builder.add_edge("resolve_scope", "retrieve_issue_evidence")
    builder.add_conditional_edges(
        "retrieve_issue_evidence",
        _after_issue_evidence,
        {
            "search_issues": "search_issues",
            "refusal": END,
        },
    )
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

    if checkpointer is None:
        return builder.compile()
    return builder.compile(checkpointer=checkpointer)
