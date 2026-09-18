from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from tests.fakes.evidence_governance import FakeEvidenceGovernanceRepository
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.issue_evidence import retrieve_issue_evidence_node
from project_agent.agent.nodes.serialization import serialize_authorized_context
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.application.ports.knowledge import KnowledgeChunk, KnowledgeRetrievalRequest
from project_agent.application.services.authorization import AuthorizedProjectContext
from project_agent.application.services.evidence_governance import (
    DocumentEvidenceMetadata,
    EvidenceGovernanceService,
)
from project_agent.application.services.issue_evidence import IssueEvidenceSelector
from project_agent.domain.access import ProjectAccessScope
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus


def _context(*, project_id: UUID, version_ids: tuple[UUID, ...]) -> AuthorizedProjectContext:
    return AuthorizedProjectContext(
        scope=ProjectAccessScope(
            company_id=uuid4(),
            user_id=uuid4(),
            allowed_client_ids=(uuid4(),),
            allowed_project_ids=(project_id,),
            allowed_document_version_ids=version_ids,
            allowed_document_categories=tuple(category.value for category in DocumentCategory),
            role_ids=("delivery_manager",),
            max_security_level=0,
            policy_version="project-membership-v1",
        ),
        project_code="PRJ-RETAIL-ALPHA",
        knowledge_space_ids=("dataset-alpha",),
    )


def _metadata(
    *,
    version_id: UUID,
    project_id: UUID,
    category: DocumentCategory,
    lifecycle: DocumentLifecycleStatus = DocumentLifecycleStatus.PUBLISHED,
    is_current: bool = True,
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> DocumentEvidenceMetadata:
    authority = {
        DocumentCategory.REQUIREMENT_BASELINE: AuthorityLevel.REQUIREMENT_BASELINE,
        DocumentCategory.APPROVED_TEST_SPEC: AuthorityLevel.APPROVED_TEST_SPEC,
    }.get(category, AuthorityLevel.APPROVED_DESIGN)
    return DocumentEvidenceMetadata(
        document_version_id=version_id,
        document_id=uuid4(),
        project_id=project_id,
        document_category=category,
        title=f"{category.value}-{version_id}",
        authority_level=authority,
        lifecycle_status=lifecycle,
        version_no=1,
        version_label="v1",
        effective_from=effective_from,
        effective_to=effective_to,
        is_current=is_current,
    )


@pytest.mark.asyncio
async def test_issue_evidence_selector_returns_only_authorized_requirement_and_test_versions(
) -> None:
    project_id = uuid4()
    requirement = uuid4()
    test_spec = uuid4()
    design = uuid4()
    other_project = uuid4()

    repo = FakeEvidenceGovernanceRepository()
    repo.records[requirement] = _metadata(
        version_id=requirement,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    repo.records[test_spec] = _metadata(
        version_id=test_spec,
        project_id=project_id,
        category=DocumentCategory.APPROVED_TEST_SPEC,
    )
    repo.records[design] = _metadata(
        version_id=design,
        project_id=project_id,
        category=DocumentCategory.APPROVED_DESIGN,
    )
    repo.records[other_project] = _metadata(
        version_id=other_project,
        project_id=uuid4(),
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    context = _context(
        project_id=project_id,
        version_ids=(requirement, test_spec, design, other_project),
    )

    selected = await IssueEvidenceSelector(repo).select_document_version_ids(
        project_id=project_id,
        context=context,
    )

    assert selected == tuple(sorted((requirement, test_spec), key=str))


@pytest.mark.asyncio
async def test_issue_evidence_selector_rejects_non_current_or_ineffective_versions() -> None:
    project_id = uuid4()
    draft = uuid4()
    old = uuid4()
    future = uuid4()
    expired = uuid4()
    repo = FakeEvidenceGovernanceRepository()
    repo.records[draft] = _metadata(
        version_id=draft,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
        lifecycle=DocumentLifecycleStatus.DRAFT,
    )
    repo.records[old] = _metadata(
        version_id=old,
        project_id=project_id,
        category=DocumentCategory.APPROVED_TEST_SPEC,
        is_current=False,
    )
    repo.records[future] = _metadata(
        version_id=future,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
        effective_from=date(2026, 9, 19),
    )
    repo.records[expired] = _metadata(
        version_id=expired,
        project_id=project_id,
        category=DocumentCategory.APPROVED_TEST_SPEC,
        effective_to=date(2026, 9, 17),
    )
    context = _context(
        project_id=project_id,
        version_ids=(draft, old, future, expired),
    )

    selected = await IssueEvidenceSelector(
        repo,
        today=lambda: date(2026, 9, 18),
    ).select_document_version_ids(project_id=project_id, context=context)

    assert selected == ()


class _RecordingKnowledge:
    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        self.chunks = chunks
        self.requests: list[KnowledgeRetrievalRequest] = []

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> list[KnowledgeChunk]:
        self.requests.append(request)
        return list(self.chunks)



async def _seed_issue_evidence_state(
    store: InMemoryQAGraphStore,
    *,
    project_id: UUID,
    context: AuthorizedProjectContext,
) -> dict[str, str]:
    run_id = uuid4()
    store.seed_query(run_id, "ERR-IMPORT-004 failed during acceptance")
    scope_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="AUTHORIZED_PROJECT_CONTEXT",
        payload=serialize_authorized_context(context),
    )
    return {
        "run_id": str(run_id),
        "project_id": str(project_id),
        "access_scope_id": str(scope_id),
    }


def _chunk(
    *,
    project_code: str,
    version_id: UUID,
    content: str,
    score: float,
    space: str = "dataset-alpha",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        project_id=project_code,
        document_version_id=str(version_id),
        content=content,
        score=score,
        knowledge_space_id=space,
        provider_ref=f"ref-{version_id}",
    )


@pytest.mark.asyncio
async def test_issue_evidence_node_preselects_governs_and_freezes_only_requirement_test() -> None:
    project_id = uuid4()
    requirement = uuid4()
    test_spec = uuid4()
    design = uuid4()
    other_project_requirement = uuid4()
    unauthorized = uuid4()
    context = _context(
        project_id=project_id,
        version_ids=(requirement, test_spec, design, other_project_requirement),
    )
    repo = FakeEvidenceGovernanceRepository()
    repo.records[requirement] = _metadata(
        version_id=requirement,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    repo.records[test_spec] = _metadata(
        version_id=test_spec,
        project_id=project_id,
        category=DocumentCategory.APPROVED_TEST_SPEC,
    )
    repo.records[design] = _metadata(
        version_id=design,
        project_id=project_id,
        category=DocumentCategory.APPROVED_DESIGN,
    )
    repo.records[other_project_requirement] = _metadata(
        version_id=other_project_requirement,
        project_id=uuid4(),
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    repo.records[unauthorized] = _metadata(
        version_id=unauthorized,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    knowledge = _RecordingKnowledge(
        [
            _chunk(
                project_code=context.project_code,
                version_id=requirement,
                content="Requirement baseline mandates UTF-8 import.",
                score=0.91,
            ),
            _chunk(
                project_code=context.project_code,
                version_id=test_spec,
                content="Approved test verifies UTF-8 CSV import.",
                score=0.88,
            ),
            # A provider that ignores the constrained version request may leak this
            # otherwise-authorized design chunk; WS5 must reject it after governance.
            _chunk(
                project_code=context.project_code,
                version_id=design,
                content="Design note is not WS5 issue evidence.",
                score=0.99,
            ),
            _chunk(
                project_code="PRJ-OTHER",
                version_id=other_project_requirement,
                content="Cross-project requirement.",
                score=1.0,
            ),
            _chunk(
                project_code=context.project_code,
                version_id=unauthorized,
                content="Unauthorized requirement.",
                score=0.97,
            ),
        ]
    )
    store = InMemoryQAGraphStore()
    state = await _seed_issue_evidence_state(store, project_id=project_id, context=context)

    result = await retrieve_issue_evidence_node(
        state,
        selector=IssueEvidenceSelector(repo, today=lambda: date(2026, 9, 18)),
        knowledge=knowledge,
        access_policy=ProjectAccessPolicy(),
        evidence_governance=EvidenceGovernanceService(
            repo,
            today=lambda: date(2026, 9, 18),
        ),
        store=store,
    )

    assert result["route"] == "issue_evidence_ready"
    assert result["last_error_code"] is None
    assert len(knowledge.requests) == 1
    assert knowledge.requests[0].document_version_ids == tuple(
        sorted((str(requirement), str(test_spec)))
    )
    assert knowledge.requests[0].knowledge_space_ids == ("dataset-alpha",)
    bundle = await store.load_governed_evidence_bundle(UUID(result["evidence_bundle_id"]))
    assert {item.document_version_id for item in bundle.evidence} == {requirement, test_spec}
    assert {item.document_category for item in bundle.evidence} <= {
        DocumentCategory.REQUIREMENT_BASELINE,
        DocumentCategory.APPROVED_TEST_SPEC,
    }
    run_id = UUID(state["run_id"])
    assert store.telemetry[run_id].retrieval_rounds == 1


@pytest.mark.asyncio
async def test_issue_evidence_node_refuses_before_retrieval_when_no_eligible_versions() -> None:
    project_id = uuid4()
    design = uuid4()
    context = _context(project_id=project_id, version_ids=(design,))
    repo = FakeEvidenceGovernanceRepository()
    repo.records[design] = _metadata(
        version_id=design,
        project_id=project_id,
        category=DocumentCategory.APPROVED_DESIGN,
    )
    knowledge = _RecordingKnowledge([])
    store = InMemoryQAGraphStore()
    state = await _seed_issue_evidence_state(store, project_id=project_id, context=context)

    result = await retrieve_issue_evidence_node(
        state,
        selector=IssueEvidenceSelector(repo, today=lambda: date(2026, 9, 18)),
        knowledge=knowledge,
        access_policy=ProjectAccessPolicy(),
        evidence_governance=EvidenceGovernanceService(repo, today=lambda: date(2026, 9, 18)),
        store=store,
    )

    assert result == {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}
    assert knowledge.requests == []
    assert store.governed_bundles == {}


@pytest.mark.asyncio
async def test_issue_evidence_node_refuses_when_provider_returns_no_authorized_chunks() -> None:
    project_id = uuid4()
    requirement = uuid4()
    context = _context(project_id=project_id, version_ids=(requirement,))
    repo = FakeEvidenceGovernanceRepository()
    repo.records[requirement] = _metadata(
        version_id=requirement,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    knowledge = _RecordingKnowledge(
        [
            _chunk(
                project_code="PRJ-OTHER",
                version_id=requirement,
                content="Cross-project content",
                score=1.0,
            )
        ]
    )
    store = InMemoryQAGraphStore()
    state = await _seed_issue_evidence_state(store, project_id=project_id, context=context)

    result = await retrieve_issue_evidence_node(
        state,
        selector=IssueEvidenceSelector(repo, today=lambda: date(2026, 9, 18)),
        knowledge=knowledge,
        access_policy=ProjectAccessPolicy(),
        evidence_governance=EvidenceGovernanceService(repo, today=lambda: date(2026, 9, 18)),
        store=store,
    )

    assert result == {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}
    assert store.governed_bundles == {}


@pytest.mark.asyncio
async def test_issue_evidence_node_refuses_when_governance_removes_every_chunk() -> None:
    project_id = uuid4()
    requirement = uuid4()
    context = _context(project_id=project_id, version_ids=(requirement,))
    selector_repo = FakeEvidenceGovernanceRepository()
    selector_repo.records[requirement] = _metadata(
        version_id=requirement,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
    )
    governance_repo = FakeEvidenceGovernanceRepository()
    governance_repo.records[requirement] = _metadata(
        version_id=requirement,
        project_id=project_id,
        category=DocumentCategory.REQUIREMENT_BASELINE,
        lifecycle=DocumentLifecycleStatus.SUPERSEDED,
    )
    knowledge = _RecordingKnowledge(
        [
            _chunk(
                project_code=context.project_code,
                version_id=requirement,
                content="Stale requirement",
                score=0.9,
            )
        ]
    )
    store = InMemoryQAGraphStore()
    state = await _seed_issue_evidence_state(store, project_id=project_id, context=context)

    result = await retrieve_issue_evidence_node(
        state,
        selector=IssueEvidenceSelector(selector_repo, today=lambda: date(2026, 9, 18)),
        knowledge=knowledge,
        access_policy=ProjectAccessPolicy(),
        evidence_governance=EvidenceGovernanceService(
            governance_repo,
            today=lambda: date(2026, 9, 18),
        ),
        store=store,
    )

    assert result == {"route": "refusal", "last_error_code": "EVIDENCE_REQUIRED"}
    assert store.governed_bundles == {}
