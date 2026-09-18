from __future__ import annotations

import importlib.util
import sys
from types import ModuleType
from typing import Any, cast

import pytest

from project_agent.agent.issue_run_graph import (
    IssueCreateRunGraphDependencies,
    IssueLookupRunGraphDependencies,
    build_issue_create_run_graph,
    build_issue_lookup_run_graph,
)
from project_agent.application.ports.qa_graph import QAGraphStorePort
from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.issue_candidates import IssueCandidateService


def test_issue_run_graph_module_exists() -> None:
    assert importlib.util.find_spec("project_agent.agent.issue_run_graph") is not None


class _FakeStateGraph:
    def __init__(self, _state_type: object) -> None:
        self.nodes: dict[str, object] = {}
        self.edges: list[tuple[object, object]] = []
        self.conditionals: list[tuple[str, object, dict[str, object]]] = []
        self.compiled_checkpointer: object | None = None

    def add_node(self, name: str, fn: object) -> None:
        self.nodes[name] = fn

    def add_edge(self, source: object, target: object) -> None:
        self.edges.append((source, target))

    def add_conditional_edges(
        self, source: str, router: object, mapping: dict[str, object]
    ) -> None:
        self.conditionals.append((source, router, mapping))

    def compile(self, *, checkpointer: object | None = None) -> _FakeStateGraph:
        self.compiled_checkpointer = checkpointer
        return self


def _install_fake_langgraph(monkeypatch: Any) -> tuple[object, object]:
    start = object()
    end = object()
    package = ModuleType("langgraph")
    graph = ModuleType("langgraph.graph")
    graph.START = start  # type: ignore[attr-defined]
    graph.END = end  # type: ignore[attr-defined]
    graph.StateGraph = _FakeStateGraph  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langgraph", package)
    monkeypatch.setitem(sys.modules, "langgraph.graph", graph)
    return start, end


def test_lookup_graph_contains_only_scope_and_search_nodes(monkeypatch: Any) -> None:
    start, end = _install_fake_langgraph(monkeypatch)
    deps = IssueLookupRunGraphDependencies(
        authorization=cast(AuthorizationService, object()),
        candidates=cast(IssueCandidateService, object()),
        store=cast(QAGraphStorePort, object()),
    )
    checkpointer = object()

    graph = build_issue_lookup_run_graph(deps, checkpointer=checkpointer)

    assert isinstance(graph, _FakeStateGraph)
    assert set(graph.nodes) == {"resolve_scope", "search_issues"}
    assert graph.edges == [
        (start, "resolve_scope"),
        ("resolve_scope", "search_issues"),
        ("search_issues", end),
    ]
    assert graph.compiled_checkpointer is checkpointer
    assert "build_issue_draft" not in graph.nodes
    assert "confirm_issue_create" not in graph.nodes
    assert "execute_issue_create" not in graph.nodes


def test_issue_create_run_graph_api_exists() -> None:
    import project_agent.agent.issue_run_graph as module

    assert hasattr(module, "IssueCreateRunGraphDependencies")
    assert hasattr(module, "build_issue_create_run_graph")


def test_create_graph_routes_evidence_before_any_draft_or_confirmation(monkeypatch: Any) -> None:
    from project_agent.agent.issue_run_graph import (
        IssueCreateRunGraphDependencies,
        build_issue_create_run_graph,
    )

    start, end = _install_fake_langgraph(monkeypatch)
    deps = IssueCreateRunGraphDependencies(
        authorization=cast(Any, object()),
        evidence_selector=cast(Any, object()),
        knowledge=cast(Any, object()),
        access_policy=cast(Any, object()),
        evidence_governance=cast(Any, object()),
        candidates=cast(Any, object()),
        drafts=cast(Any, object()),
        confirmations=cast(Any, object()),
        creation=cast(Any, object()),
        store=cast(Any, object()),
    )

    graph = build_issue_create_run_graph(deps)

    assert isinstance(graph, _FakeStateGraph)
    assert set(graph.nodes) == {
        "resolve_scope",
        "retrieve_issue_evidence",
        "search_issues",
        "build_issue_draft",
        "confirm_issue_create",
        "execute_issue_create",
    }
    assert graph.edges[:2] == [
        (start, "resolve_scope"),
        ("resolve_scope", "retrieve_issue_evidence"),
    ]
    evidence_conditional = next(
        item for item in graph.conditionals if item[0] == "retrieve_issue_evidence"
    )
    assert evidence_conditional[2] == {
        "search_issues": "search_issues",
        "refusal": end,
    }
    assert ("search_issues", "build_issue_draft") in graph.edges
    assert ("build_issue_draft", "confirm_issue_create") in graph.edges
    assert ("execute_issue_create", end) in graph.edges


def test_evidence_refusal_router_never_reaches_draft_path() -> None:
    from project_agent.agent.issue_run_graph import _after_issue_evidence

    assert _after_issue_evidence({"route": "refusal"}) == "refusal"
    assert _after_issue_evidence({"route": "issue_evidence_ready"}) == "search_issues"


@pytest.mark.asyncio
async def test_real_lookup_graph_authorizes_and_remains_business_read_only() -> None:
    pytest.importorskip("langgraph", reason="requires synchronized LangGraph runtime")
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from tests.fakes.authorization import FakeProjectAuthorizationRepository
    from tests.fakes.project_tracker import SandboxProjectTrackerAdapter
    from tests.fakes.qa_graph_store import InMemoryQAGraphStore

    from project_agent.application.services.authorization import (
        AuthorizationService,
        MembershipAccessRecord,
    )
    from project_agent.application.services.identifier_extractor import IdentifierExtractor
    from project_agent.application.services.issue_candidates import IssueCandidateService
    from project_agent.domain.enums import ProjectRole

    now = datetime.now(UTC)
    run_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    client_id = uuid4()
    company_id = uuid4()
    auth_repo = FakeProjectAuthorizationRepository()
    auth_repo.memberships[(user_id, project_id)] = MembershipAccessRecord(
        company_id=company_id,
        client_id=client_id,
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        role=ProjectRole.DEVELOPER,
        valid_from=now - timedelta(days=1),
        valid_to=None,
    )
    tracker = SandboxProjectTrackerAdapter()
    tracker.seed_issue(
        project_id=str(project_id),
        issue_key="ALPHA-101",
        title="Import failed",
        description="ERR-IMPORT-004",
        status="OPEN",
        module="import",
        error_code="ERR-IMPORT-004",
    )
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "模块: import ERR-IMPORT-004")
    graph = build_issue_lookup_run_graph(
        IssueLookupRunGraphDependencies(
            authorization=AuthorizationService(auth_repo),
            candidates=IssueCandidateService(
                tracker=tracker,
                extractor=IdentifierExtractor(),
            ),
            store=store,
        )
    )

    result = await graph.ainvoke(
        {
            "run_id": str(run_id),
            "thread_id": str(uuid4()),
            "user_id": str(user_id),
            "project_id": str(project_id),
            "route": None,
            "last_error_code": None,
        }
    )

    assert result["route"] == "issue_candidates"
    assert result["issue_candidate_id"]
    assert tracker.create_side_effect_count == 0
    assert tracker.search_requests[-1].project_id == str(project_id)


@pytest.mark.asyncio
async def test_real_create_graph_stops_at_evidence_required_before_draft() -> None:
    pytest.importorskip("langgraph", reason="requires synchronized LangGraph runtime")
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from tests.fakes.authorization import FakeProjectAuthorizationRepository
    from tests.fakes.evidence_governance import FakeEvidenceGovernanceRepository
    from tests.fakes.issue_workflow import FakeIssueWorkflowRepository
    from tests.fakes.knowledge import FakeKnowledgePort
    from tests.fakes.project_tracker import SandboxProjectTrackerAdapter
    from tests.fakes.qa_graph_store import InMemoryQAGraphStore

    from project_agent.agent.policies.access import ProjectAccessPolicy
    from project_agent.application.services.authorization import (
        AuthorizationService,
        MembershipAccessRecord,
    )
    from project_agent.application.services.evidence_governance import EvidenceGovernanceService
    from project_agent.application.services.identifier_extractor import IdentifierExtractor
    from project_agent.application.services.issue_candidates import IssueCandidateService
    from project_agent.application.services.issue_confirmation import IssueConfirmationService
    from project_agent.application.services.issue_drafts import IssueDraftService
    from project_agent.application.services.issue_evidence import IssueEvidenceSelector
    from project_agent.domain.enums import ProjectRole

    now = datetime.now(UTC)
    run_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    auth_repo = FakeProjectAuthorizationRepository()
    auth_repo.memberships[(user_id, project_id)] = MembershipAccessRecord(
        company_id=uuid4(),
        client_id=uuid4(),
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        role=ProjectRole.DEVELOPER,
        valid_from=now - timedelta(days=1),
        valid_to=None,
    )
    auth_repo.knowledge_spaces[project_id] = ("dataset-alpha",)
    evidence_repo = FakeEvidenceGovernanceRepository()
    tracker = SandboxProjectTrackerAdapter()
    workflow_repo = FakeIssueWorkflowRepository()
    drafts = IssueDraftService(workflow_repo)
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "模块: import ERR-IMPORT-004")
    graph = build_issue_create_run_graph(
        IssueCreateRunGraphDependencies(
            authorization=AuthorizationService(auth_repo),
            evidence_selector=IssueEvidenceSelector(evidence_repo),
            knowledge=FakeKnowledgePort(),
            access_policy=ProjectAccessPolicy(),
            evidence_governance=EvidenceGovernanceService(evidence_repo),
            candidates=IssueCandidateService(
                tracker=tracker,
                extractor=IdentifierExtractor(),
            ),
            drafts=drafts,
            confirmations=IssueConfirmationService(workflow_repo, drafts=drafts),
            creation=cast(Any, object()),
            store=store,
        )
    )

    result = await graph.ainvoke(
        {
            "run_id": str(run_id),
            "thread_id": str(uuid4()),
            "user_id": str(user_id),
            "project_id": str(project_id),
            "route": None,
            "last_error_code": None,
        }
    )

    assert result["route"] == "refusal"
    assert result["last_error_code"] == "EVIDENCE_REQUIRED"
    assert workflow_repo.drafts == {}
    assert workflow_repo.confirmations == {}
    assert tracker.search_requests == []
    assert tracker.create_side_effect_count == 0


@pytest.mark.asyncio
async def test_real_create_graph_interrupt_exposes_frozen_evidence_ids() -> None:
    pytest.importorskip("langgraph", reason="requires synchronized LangGraph runtime")
    from datetime import UTC, date, datetime, timedelta
    from uuid import UUID, uuid4

    try:
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:  # pragma: no cover - compatibility with older LangGraph aliases
        from langgraph.checkpoint.memory import MemorySaver as InMemorySaver  # type: ignore

    from tests.fakes.authorization import FakeProjectAuthorizationRepository
    from tests.fakes.evidence_governance import FakeEvidenceGovernanceRepository
    from tests.fakes.issue_workflow import FakeIssueWorkflowRepository
    from tests.fakes.knowledge import FakeKnowledgePort
    from tests.fakes.project_tracker import SandboxProjectTrackerAdapter
    from tests.fakes.qa_graph_store import InMemoryQAGraphStore

    from project_agent.agent.policies.access import ProjectAccessPolicy
    from project_agent.application.services.authorization import (
        AuthorizationService,
        DocumentAccessRecord,
        MembershipAccessRecord,
    )
    from project_agent.application.services.evidence_governance import (
        DocumentEvidenceMetadata,
        EvidenceGovernanceService,
    )
    from project_agent.application.services.identifier_extractor import IdentifierExtractor
    from project_agent.application.services.issue_candidates import IssueCandidateService
    from project_agent.application.services.issue_confirmation import IssueConfirmationService
    from project_agent.application.services.issue_drafts import IssueDraftService
    from project_agent.application.services.issue_evidence import IssueEvidenceSelector
    from project_agent.domain.enums import (
        AuthorityLevel,
        DocumentCategory,
        DocumentLifecycleStatus,
        ProjectRole,
    )

    now = datetime.now(UTC)
    run_id = uuid4()
    thread_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    version_id = uuid4()
    auth_repo = FakeProjectAuthorizationRepository()
    auth_repo.memberships[(user_id, project_id)] = MembershipAccessRecord(
        company_id=uuid4(),
        client_id=uuid4(),
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        role=ProjectRole.DEVELOPER,
        valid_from=now - timedelta(days=1),
        valid_to=None,
    )
    auth_repo.documents[project_id] = [
        DocumentAccessRecord(
            document_version_id=version_id,
            document_category=DocumentCategory.REQUIREMENT_BASELINE.value,
        )
    ]
    auth_repo.knowledge_spaces[project_id] = ("dataset-alpha",)
    evidence_repo = FakeEvidenceGovernanceRepository()
    evidence_repo.records[version_id] = DocumentEvidenceMetadata(
        document_version_id=version_id,
        document_id=uuid4(),
        project_id=project_id,
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        title="Import requirement",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        version_no=1,
        version_label="v1",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        is_current=True,
    )
    knowledge = FakeKnowledgePort()
    knowledge.add_chunk(
        project_id="PRJ-RETAIL-ALPHA",
        document_version_id=str(version_id),
        content="ERR-IMPORT-004 must create an issue during acceptance failure.",
        score=0.95,
        knowledge_space_id="dataset-alpha",
        provider_ref="requirement-1",
    )
    tracker = SandboxProjectTrackerAdapter()
    workflow_repo = FakeIssueWorkflowRepository()
    drafts = IssueDraftService(workflow_repo)
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "模块: import ERR-IMPORT-004")
    graph = build_issue_create_run_graph(
        IssueCreateRunGraphDependencies(
            authorization=AuthorizationService(auth_repo),
            evidence_selector=IssueEvidenceSelector(evidence_repo),
            knowledge=knowledge,
            access_policy=ProjectAccessPolicy(),
            evidence_governance=EvidenceGovernanceService(evidence_repo),
            candidates=IssueCandidateService(
                tracker=tracker,
                extractor=IdentifierExtractor(),
            ),
            drafts=drafts,
            confirmations=IssueConfirmationService(workflow_repo, drafts=drafts),
            creation=cast(Any, object()),
            store=store,
        ),
        checkpointer=InMemorySaver(),
    )

    result = await graph.ainvoke(
        {
            "run_id": str(run_id),
            "thread_id": str(thread_id),
            "user_id": str(user_id),
            "project_id": str(project_id),
            "route": None,
            "last_error_code": None,
        },
        {"configurable": {"thread_id": str(thread_id)}},
    )

    interrupts = result["__interrupt__"]
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert payload["request_payload_hash"]
    assert payload["request_id"]
    assert payload["draft_id"]
    assert payload["evidence_ids"]
    draft = workflow_repo.drafts[UUID(str(payload["draft_id"]))]
    assert tuple(payload["evidence_ids"]) == draft.evidence_ids
    assert tracker.create_side_effect_count == 0
