from __future__ import annotations

from datetime import date
from uuid import uuid4

from tests.fakes.evidence_governance import FakeEvidenceGovernanceRepository

from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.application.services.evidence_governance import (
    DocumentEvidenceMetadata,
    EvidenceGovernanceService,
)
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus


def _metadata(
    *,
    version_id,
    project_id,
    authority,
    version_no=1,
    lifecycle=DocumentLifecycleStatus.PUBLISHED,
    is_current=True,
    effective_from=None,
    effective_to=None,
):
    return DocumentEvidenceMetadata(
        document_version_id=version_id,
        document_id=uuid4(),
        project_id=project_id,
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        title=f"doc-{version_no}",
        authority_level=authority,
        lifecycle_status=lifecycle,
        version_no=version_no,
        version_label=f"v{version_no}",
        effective_from=effective_from,
        effective_to=effective_to,
        is_current=is_current,
    )


def _chunk(*, project_code, version_id, content, score, metadata=None):
    return KnowledgeChunk(
        project_id=project_code,
        document_version_id=str(version_id),
        knowledge_space_id="dataset-alpha",
        provider_ref=f"ref-{score}",
        content=content,
        score=score,
        metadata=metadata or {},
    )


def test_authority_order_matches_frozen_business_policy() -> None:
    assert EvidenceGovernanceService.AUTHORITY_ORDER == (
        AuthorityLevel.SIGNED_SCOPE,
        AuthorityLevel.APPROVED_CHANGE,
        AuthorityLevel.REQUIREMENT_BASELINE,
        AuthorityLevel.APPROVED_MEETING_MINUTES,
        AuthorityLevel.APPROVED_DESIGN,
        AuthorityLevel.APPROVED_TEST_SPEC,
        AuthorityLevel.RELEASE_RUNBOOK,
        AuthorityLevel.ISSUE_RECORD,
        AuthorityLevel.INFORMAL_NOTE,
    )


async def test_higher_authority_beats_higher_retrieval_score() -> None:
    project_id = uuid4()
    requirement_version = uuid4()
    issue_version = uuid4()
    repo = FakeEvidenceGovernanceRepository()
    repo.records[requirement_version] = _metadata(
        version_id=requirement_version,
        project_id=project_id,
        authority=AuthorityLevel.REQUIREMENT_BASELINE,
    )
    repo.records[issue_version] = _metadata(
        version_id=issue_version,
        project_id=project_id,
        authority=AuthorityLevel.ISSUE_RECORD,
    )
    service = EvidenceGovernanceService(repo, today=lambda: date(2026, 8, 8))

    pack = await service.pack(
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        chunks=[
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=issue_version,
                content="issue evidence",
                score=0.99,
            ),
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=requirement_version,
                content="requirement evidence",
                score=0.71,
            ),
        ],
    )

    assert [item.authority_level for item in pack.evidence] == [
        AuthorityLevel.REQUIREMENT_BASELINE,
        AuthorityLevel.ISSUE_RECORD,
    ]
    assert [item.label for item in pack.evidence] == ["E1", "E2"]


async def test_non_current_non_published_and_expired_evidence_are_removed() -> None:
    project_id = uuid4()
    current = uuid4()
    old = uuid4()
    draft = uuid4()
    expired = uuid4()
    repo = FakeEvidenceGovernanceRepository()
    repo.records[current] = _metadata(
        version_id=current,
        project_id=project_id,
        authority=AuthorityLevel.REQUIREMENT_BASELINE,
    )
    repo.records[old] = _metadata(
        version_id=old,
        project_id=project_id,
        authority=AuthorityLevel.SIGNED_SCOPE,
        is_current=False,
    )
    repo.records[draft] = _metadata(
        version_id=draft,
        project_id=project_id,
        authority=AuthorityLevel.SIGNED_SCOPE,
        lifecycle=DocumentLifecycleStatus.DRAFT,
    )
    repo.records[expired] = _metadata(
        version_id=expired,
        project_id=project_id,
        authority=AuthorityLevel.SIGNED_SCOPE,
        effective_to=date(2026, 8, 7),
    )
    service = EvidenceGovernanceService(repo, today=lambda: date(2026, 8, 8))

    pack = await service.pack(
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        chunks=[
            _chunk(project_code="PRJ-RETAIL-ALPHA", version_id=value, content=str(value), score=0.8)
            for value in (current, old, draft, expired)
        ],
    )

    assert [item.document_version_id for item in pack.evidence] == [current]


async def test_equal_top_authority_explicit_conflict_is_marked_unresolved() -> None:
    project_id = uuid4()
    v1 = uuid4()
    v2 = uuid4()
    repo = FakeEvidenceGovernanceRepository()
    repo.records[v1] = _metadata(
        version_id=v1, project_id=project_id, authority=AuthorityLevel.APPROVED_CHANGE
    )
    repo.records[v2] = _metadata(
        version_id=v2, project_id=project_id, authority=AuthorityLevel.APPROVED_CHANGE
    )
    service = EvidenceGovernanceService(repo, today=lambda: date(2026, 8, 8))

    pack = await service.pack(
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        chunks=[
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=v1,
                content="锁定 30 分钟",
                score=0.9,
                metadata={
                    "conflict_key": "REQ-3.2.1.lock_minutes",
                    "claim_value": "30",
                },
            ),
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=v2,
                content="锁定 60 分钟",
                score=0.8,
                metadata={
                    "conflict_key": "REQ-3.2.1.lock_minutes",
                    "claim_value": "60",
                },
            ),
        ],
    )

    assert pack.unresolved_conflicts == {"REQ-3.2.1.lock_minutes": ("E1", "E2")}
    assert all(item.unresolved_conflict for item in pack.evidence)


async def test_higher_authority_resolves_explicit_conflict_and_suppresses_lower_value() -> None:
    project_id = uuid4()
    high = uuid4()
    low = uuid4()
    repo = FakeEvidenceGovernanceRepository()
    repo.records[high] = _metadata(
        version_id=high, project_id=project_id, authority=AuthorityLevel.APPROVED_CHANGE
    )
    repo.records[low] = _metadata(
        version_id=low, project_id=project_id, authority=AuthorityLevel.ISSUE_RECORD
    )
    service = EvidenceGovernanceService(repo, today=lambda: date(2026, 8, 8))

    pack = await service.pack(
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        chunks=[
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=low,
                content="60",
                score=0.99,
                metadata={"conflict_key": "lock", "claim_value": "60"},
            ),
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=high,
                content="30",
                score=0.70,
                metadata={"conflict_key": "lock", "claim_value": "30"},
            ),
        ],
    )

    assert pack.unresolved_conflicts == {}
    assert [item.document_version_id for item in pack.evidence] == [high]

async def test_unresolved_conflict_group_is_not_split_by_evidence_limit() -> None:
    project_id = uuid4()
    v1 = uuid4()
    v2 = uuid4()
    repo = FakeEvidenceGovernanceRepository()
    repo.records[v1] = _metadata(
        version_id=v1,
        project_id=project_id,
        authority=AuthorityLevel.APPROVED_CHANGE,
    )
    repo.records[v2] = _metadata(
        version_id=v2,
        project_id=project_id,
        authority=AuthorityLevel.APPROVED_CHANGE,
    )
    service = EvidenceGovernanceService(
        repo,
        today=lambda: date(2026, 8, 8),
        max_evidence=1,
    )

    pack = await service.pack(
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        chunks=[
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=v1,
                content="锁定 30 分钟",
                score=0.9,
                metadata={"conflict_key": "lock", "claim_value": "30"},
            ),
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=v2,
                content="锁定 60 分钟",
                score=0.8,
                metadata={"conflict_key": "lock", "claim_value": "60"},
            ),
        ],
    )

    assert len(pack.evidence) == 2
    assert pack.unresolved_conflicts == {"lock": ("E1", "E2")}

async def test_unresolved_conflict_below_normal_cutoff_is_still_preserved() -> None:
    project_id = uuid4()
    top = uuid4()
    v1 = uuid4()
    v2 = uuid4()
    repo = FakeEvidenceGovernanceRepository()
    repo.records[top] = _metadata(
        version_id=top,
        project_id=project_id,
        authority=AuthorityLevel.SIGNED_SCOPE,
    )
    repo.records[v1] = _metadata(
        version_id=v1,
        project_id=project_id,
        authority=AuthorityLevel.APPROVED_CHANGE,
    )
    repo.records[v2] = _metadata(
        version_id=v2,
        project_id=project_id,
        authority=AuthorityLevel.APPROVED_CHANGE,
    )
    service = EvidenceGovernanceService(
        repo,
        today=lambda: date(2026, 8, 8),
        max_evidence=1,
    )

    pack = await service.pack(
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        chunks=[
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=top,
                content="最高权威范围说明",
                score=0.99,
            ),
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=v1,
                content="锁定 30 分钟",
                score=0.8,
                metadata={"conflict_key": "lock", "claim_value": "30"},
            ),
            _chunk(
                project_code="PRJ-RETAIL-ALPHA",
                version_id=v2,
                content="锁定 60 分钟",
                score=0.7,
                metadata={"conflict_key": "lock", "claim_value": "60"},
            ),
        ],
    )

    assert len(pack.evidence) == 3
    assert set(pack.unresolved_conflicts) == {"lock"}
