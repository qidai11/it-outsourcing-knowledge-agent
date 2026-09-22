from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from tests.fakes.issue_workflow import FakeIssueWorkflowRepository
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.build_issue_draft import build_issue_draft_node
from project_agent.application.services.issue_candidates import (
    IssueCandidate,
    IssueCandidateQuery,
    IssueCandidateResult,
)
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.evidence import FrozenEvidence, FrozenEvidenceBundle
from project_agent.domain.issues import IssueDraftStatus


@pytest.mark.asyncio
async def test_create_draft_persists_possible_duplicate_links() -> None:
    repo = FakeIssueWorkflowRepository()
    service = IssueDraftService(repo)
    run_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    candidates = IssueCandidateResult(
        query=IssueCandidateQuery(
            project_id=str(project_id),
            title="CSV import fails",
            description="ERR-IMPORT-004",
            error_code="ERR-IMPORT-004",
        ),
        possible_duplicates=(
            IssueCandidate(
                project_id=str(project_id),
                issue_key="ALPHA-101",
                title="CSV import fails",
                description="encoding",
                status="OPEN",
                issue_type="bug",
                priority="high",
                score=1010.0,
                reasons=("exact_error_code",),
            ),
        ),
    )

    draft = await service.create_from_text(
        run_id=run_id,
        project_id=project_id,
        created_by=user_id,
        text="模块: import\nCSV import fails with ERR-IMPORT-004 in UAT",
        candidates=candidates,
    )

    assert draft.status is IssueDraftStatus.DRAFT
    assert draft.issue_type == "bug"
    assert draft.module == "import"
    assert draft.description.startswith("模块: import")
    links = await repo.list_candidate_links(draft.id)
    assert [item.issue_key for item in links] == ["ALPHA-101"]
    assert links[0].reasons == ("exact_error_code",)


@pytest.mark.asyncio
async def test_request_id_is_draft_uuid_and_payload_is_stable() -> None:
    repo = FakeIssueWorkflowRepository()
    service = IssueDraftService(repo)
    draft = await service.create_from_text(
        run_id=uuid4(),
        project_id=uuid4(),
        created_by=uuid4(),
        text="ERR-IMPORT-004 upload failed",
    )

    first = service.build_create_request(draft)
    second = service.build_create_request(draft)

    assert first.request_id == str(draft.id)
    assert first == second
    assert service.payload_hash(first) == service.payload_hash(second)


@pytest.mark.asyncio
async def test_create_draft_persists_frozen_evidence_ids() -> None:
    repo = FakeIssueWorkflowRepository()
    service = IssueDraftService(repo)
    evidence_ids = (str(uuid4()), str(uuid4()))

    draft = await service.create_from_text(
        run_id=uuid4(),
        project_id=uuid4(),
        created_by=uuid4(),
        text="ERR-IMPORT-004 failed",
        evidence_ids=evidence_ids,
    )

    assert draft.evidence_ids == evidence_ids
    assert repo.drafts[draft.id].evidence_ids == evidence_ids


def _frozen_evidence(*, project_id: UUID, version_id: UUID, snapshot_id: UUID) -> FrozenEvidence:
    return FrozenEvidence(
        snapshot_id=snapshot_id,
        label="E1",
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        document_version_id=version_id,
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        document_title="Requirement baseline",
        version_no=1,
        version_label="v1",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        is_current=True,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        content="UTF-8 import is required.",
        content_hash="a" * 64,
        score=0.9,
        knowledge_space_id="dataset-alpha",
        provider_ref="chunk-1",
        page_no=1,
        section="3.2.1",
        conflict_key=None,
        claim_value=None,
        unresolved_conflict=False,
    )


@pytest.mark.asyncio
async def test_build_issue_draft_node_binds_frozen_snapshot_ids() -> None:
    run_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    snapshot_ids = (uuid4(), uuid4())
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "模块: import\nERR-IMPORT-004 failed")
    bundle_id = uuid4()
    store.governed_bundles[bundle_id] = FrozenEvidenceBundle(
        evidence=(
            _frozen_evidence(
                project_id=project_id,
                version_id=uuid4(),
                snapshot_id=snapshot_ids[0],
            ),
            _frozen_evidence(
                project_id=project_id,
                version_id=uuid4(),
                snapshot_id=snapshot_ids[1],
            ),
        ),
        unresolved_conflicts={},
    )
    repo = FakeIssueWorkflowRepository()

    result = await build_issue_draft_node(
        {
            "run_id": str(run_id),
            "project_id": str(project_id),
            "user_id": str(user_id),
            "access_scope_id": str(uuid4()),
            "evidence_bundle_id": str(bundle_id),
        },
        drafts=IssueDraftService(repo),
        store=store,
    )

    draft = repo.drafts[UUID(result["issue_draft_id"])]
    assert draft.evidence_ids == tuple(str(value) for value in snapshot_ids)


@pytest.mark.asyncio
async def test_build_issue_draft_node_preserves_empty_evidence_without_frozen_bundle() -> None:
    run_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "ERR-IMPORT-004 failed")
    repo = FakeIssueWorkflowRepository()

    result = await build_issue_draft_node(
        {
            "run_id": str(run_id),
            "project_id": str(project_id),
            "user_id": str(user_id),
            "access_scope_id": str(uuid4()),
        },
        drafts=IssueDraftService(repo),
        store=store,
    )

    assert repo.drafts[UUID(result["issue_draft_id"])].evidence_ids == ()
