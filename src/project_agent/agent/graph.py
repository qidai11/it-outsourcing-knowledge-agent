from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_agent.agent.nodes.analyze_query import QueryAnalysisService
from project_agent.agent.nodes.citation_guard import citation_guard_node
from project_agent.agent.nodes.clarify import clarify_project_node
from project_agent.agent.nodes.generate_answer import generate_answer_node
from project_agent.agent.nodes.govern_evidence import govern_evidence_node
from project_agent.agent.nodes.grade_retrieval import grade_retrieval_node
from project_agent.agent.nodes.identifier_node import resolve_identifiers_node
from project_agent.agent.nodes.load_prompt import load_prompt_snapshot_node
from project_agent.agent.nodes.query_analysis_node import analyze_query_node
from project_agent.agent.nodes.refuse import refuse_node
from project_agent.agent.nodes.resolve_identifiers import ExactIdentifierResolver
from project_agent.agent.nodes.resolve_scope import resolve_scope_node
from project_agent.agent.nodes.retrieve import retrieve_node
from project_agent.agent.nodes.revise_answer import revise_answer_node
from project_agent.agent.nodes.select_project import ProjectSelectionService, select_project_node
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.agent.state import AgentState
from project_agent.application.ports.knowledge import KnowledgeRetrievalPort
from project_agent.application.ports.llm import StructuredLLMPort, StructuredLLMUsagePort
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.citation_guard import CitationGuard
from project_agent.application.services.evidence_governance import EvidenceGovernanceService
from project_agent.application.services.prompt_config import PromptConfigService


@dataclass(frozen=True, slots=True)
class QAGraphDependencies:
    authorization: AuthorizationService
    query_analysis: QueryAnalysisService
    exact_resolver: ExactIdentifierResolver
    knowledge: KnowledgeRetrievalPort
    access_policy: ProjectAccessPolicy
    prompt_config: PromptConfigService
    evidence_governance: EvidenceGovernanceService
    citation_guard: CitationGuard
    llm: StructuredLLMPort
    llm_usage: StructuredLLMUsagePort
    store: QAGraphStorePort
    model_alias: str


def _after_project_selection(state: AgentState) -> str:
    route = state.get("route")
    if route == "clarification":
        return "clarify_project"
    if route == "refusal":
        return "refuse"
    return "resolve_scope"


def _after_retrieval(state: AgentState) -> str:
    return "grade_retrieval" if state.get("route") == "grade_retrieval" else "refuse"


def _after_retrieval_grade(state: AgentState) -> str:
    route = state.get("route")
    if route == "govern_evidence":
        return "govern_evidence"
    if route == "retrieve_again":
        return "retrieve"
    return "refuse"


def _after_governance(state: AgentState) -> str:
    return "generate_answer" if state.get("route") == "generate_answer" else "refuse"


def _after_citation_guard(state: AgentState) -> str:
    route = state.get("route")
    if route == "answered":
        return "answered"
    if route == "revise_answer":
        return "revise_answer"
    return "refuse"


def build_project_qa_graph(
    deps: QAGraphDependencies,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the minimal project knowledge-QA workflow with LangGraph."""

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - depends on synchronized runtime
        raise RuntimeError("langgraph is required to compile the QA graph") from exc

    builder = StateGraph(AgentState)

    async def load_prompt(state: AgentState) -> AgentState:
        return await load_prompt_snapshot_node(
            state,
            prompt_config=deps.prompt_config,
            store=deps.store,
            model_alias=deps.model_alias,
        )

    async def analyze(state: AgentState) -> AgentState:
        return await analyze_query_node(
            state,
            query_analysis=deps.query_analysis,
            store=deps.store,
        )

    async def select_project(state: AgentState) -> AgentState:
        return await select_project_node(
            state,
            selector=ProjectSelectionService(deps.authorization),
            store=deps.store,
        )

    async def scope(state: AgentState) -> AgentState:
        return await resolve_scope_node(
            state,
            authorization=deps.authorization,
            store=deps.store,
        )

    async def identifiers(state: AgentState) -> AgentState:
        return await resolve_identifiers_node(
            state,
            exact_resolver=deps.exact_resolver,
            store=deps.store,
        )

    async def retrieve(state: AgentState) -> AgentState:
        return await retrieve_node(
            state,
            knowledge=deps.knowledge,
            access_policy=deps.access_policy,
            store=deps.store,
        )

    async def grade_retrieval(state: AgentState) -> AgentState:
        return await grade_retrieval_node(
            state,
            llm=deps.llm,
            llm_usage=deps.llm_usage,
            store=deps.store,
            model_alias=deps.model_alias,
        )

    async def govern(state: AgentState) -> AgentState:
        return await govern_evidence_node(
            state,
            evidence_governance=deps.evidence_governance,
            store=deps.store,
        )

    async def answer(state: AgentState) -> AgentState:
        return await generate_answer_node(
            state,
            llm=deps.llm,
            llm_usage=deps.llm_usage,
            store=deps.store,
            model_alias=deps.model_alias,
        )

    async def guard_citations(state: AgentState) -> AgentState:
        return await citation_guard_node(
            state,
            guard=deps.citation_guard,
            store=deps.store,
        )

    async def revise(state: AgentState) -> AgentState:
        return await revise_answer_node(
            state,
            llm=deps.llm,
            llm_usage=deps.llm_usage,
            store=deps.store,
            model_alias=deps.model_alias,
        )

    async def refusal(state: AgentState) -> AgentState:
        return await refuse_node(state, store=deps.store)

    async def clarification(state: AgentState) -> AgentState:
        return await clarify_project_node(state, store=deps.store)

    builder.add_node("load_prompt", load_prompt)
    builder.add_node("analyze_query", analyze)
    builder.add_node("select_project", select_project)
    builder.add_node("resolve_scope", scope)
    builder.add_node("resolve_identifiers", identifiers)
    builder.add_node("retrieve", retrieve)
    builder.add_node("grade_retrieval", grade_retrieval)
    builder.add_node("govern_evidence", govern)
    builder.add_node("generate_answer", answer)
    builder.add_node("citation_guard", guard_citations)
    builder.add_node("revise_answer", revise)
    builder.add_node("refuse", refusal)
    builder.add_node("clarify_project", clarification)

    builder.add_edge(START, "load_prompt")
    builder.add_edge("load_prompt", "analyze_query")
    builder.add_edge("analyze_query", "select_project")
    builder.add_conditional_edges(
        "select_project",
        _after_project_selection,
        {
            "resolve_scope": "resolve_scope",
            "clarify_project": "clarify_project",
            "refuse": "refuse",
        },
    )
    builder.add_edge("resolve_scope", "resolve_identifiers")
    builder.add_edge("resolve_identifiers", "retrieve")
    builder.add_conditional_edges(
        "retrieve",
        _after_retrieval,
        {
            "grade_retrieval": "grade_retrieval",
            "refuse": "refuse",
        },
    )
    builder.add_conditional_edges(
        "grade_retrieval",
        _after_retrieval_grade,
        {
            "govern_evidence": "govern_evidence",
            "retrieve": "retrieve",
            "refuse": "refuse",
        },
    )
    builder.add_conditional_edges(
        "govern_evidence",
        _after_governance,
        {
            "generate_answer": "generate_answer",
            "refuse": "refuse",
        },
    )
    builder.add_edge("generate_answer", "citation_guard")
    builder.add_conditional_edges(
        "citation_guard",
        _after_citation_guard,
        {
            "answered": END,
            "revise_answer": "revise_answer",
            "refuse": "refuse",
        },
    )
    builder.add_edge("revise_answer", "citation_guard")
    builder.add_edge("refuse", END)
    builder.add_edge("clarify_project", END)

    if checkpointer is None:
        return builder.compile()
    return builder.compile(checkpointer=checkpointer)
