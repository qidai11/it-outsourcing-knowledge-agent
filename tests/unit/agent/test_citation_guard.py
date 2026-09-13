from __future__ import annotations

from dataclasses import replace
from datetime import date
from uuid import uuid4

from project_agent.agent.nodes.models import GroundedAnswerDraft
from project_agent.application.services.citation_guard import CitationGuard
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.evidence import FrozenEvidence, FrozenEvidenceBundle


def _evidence(label: str, *, project_id=None, conflict_key=None, unresolved=False) -> FrozenEvidence:
    return FrozenEvidence(
        snapshot_id=uuid4(),
        label=label,
        project_id=project_id or uuid4(),
        project_code="PRJ-RETAIL-ALPHA",
        document_version_id=uuid4(),
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        document_title="Requirement",
        version_no=2,
        version_label="v2",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        is_current=True,
        effective_from=None,
        effective_to=None,
        content="连续登录失败 5 次后锁定账户 30 分钟。",
        content_hash="hash",
        score=0.9,
        knowledge_space_id="dataset-alpha",
        provider_ref="chunk-1",
        page_no=3,
        section="3.2.1",
        conflict_key=conflict_key,
        claim_value="30" if conflict_key else None,
        unresolved_conflict=unresolved,
    )


def test_valid_claim_citations_have_full_coverage() -> None:
    project_id = uuid4()
    e1 = _evidence("E1", project_id=project_id)
    bundle = FrozenEvidenceBundle(evidence=(e1,), unresolved_conflicts={})
    draft = GroundedAnswerDraft.model_validate({
        "claims": [{"text": "连续登录失败 5 次后锁定账户 30 分钟。", "evidence_ids": ["E1"]}],
        "conflict_disclosure": None,
    })

    result = CitationGuard().validate(draft, bundle=bundle, project_id=project_id)

    assert result.valid is True
    assert result.coverage == 1.0
    assert result.used_evidence_ids == ("E1",)


def test_unknown_citation_id_is_rejected() -> None:
    project_id = uuid4()
    bundle = FrozenEvidenceBundle(evidence=(_evidence("E1", project_id=project_id),), unresolved_conflicts={})
    draft = GroundedAnswerDraft.model_validate({
        "claims": [{"text": "事实", "evidence_ids": ["E99"]}],
        "conflict_disclosure": None,
    })

    result = CitationGuard().validate(draft, bundle=bundle, project_id=project_id)

    assert result.valid is False
    assert "UNKNOWN_EVIDENCE_ID:E99" in result.errors


def test_claim_without_citation_is_rejected() -> None:
    project_id = uuid4()
    bundle = FrozenEvidenceBundle(evidence=(_evidence("E1", project_id=project_id),), unresolved_conflicts={})
    draft = GroundedAnswerDraft.model_validate({
        "claims": [{"text": "事实", "evidence_ids": []}],
        "conflict_disclosure": None,
    })

    result = CitationGuard().validate(draft, bundle=bundle, project_id=project_id)

    assert result.valid is False
    assert result.coverage == 0.0
    assert "UNCITED_CLAIM:1" in result.errors


def test_cross_project_snapshot_is_rejected_even_with_valid_label() -> None:
    requested_project = uuid4()
    foreign = _evidence("E1", project_id=uuid4())
    bundle = FrozenEvidenceBundle(evidence=(foreign,), unresolved_conflicts={})
    draft = GroundedAnswerDraft.model_validate({
        "claims": [{"text": "事实", "evidence_ids": ["E1"]}],
        "conflict_disclosure": None,
    })

    result = CitationGuard().validate(draft, bundle=bundle, project_id=requested_project)

    assert result.valid is False
    assert "CROSS_PROJECT_EVIDENCE:E1" in result.errors


def test_unresolved_conflict_requires_disclosure_citing_both_sides() -> None:
    project_id = uuid4()
    e1 = _evidence("E1", project_id=project_id, conflict_key="lock", unresolved=True)
    e2 = replace(e1, snapshot_id=uuid4(), label="E2", content="锁定 60 分钟", claim_value="60")
    bundle = FrozenEvidenceBundle(evidence=(e1, e2), unresolved_conflicts={"lock": ("E1", "E2")})
    draft = GroundedAnswerDraft.model_validate({
        "claims": [{"text": "存在两个已批准版本的冲突。", "evidence_ids": ["E1", "E2"]}],
        "conflict_disclosure": None,
    })

    result = CitationGuard().validate(draft, bundle=bundle, project_id=project_id)

    assert result.valid is False
    assert "MISSING_CONFLICT_DISCLOSURE:lock" in result.errors

    disclosed = GroundedAnswerDraft.model_validate({
        "claims": [{"text": "当前证据存在冲突。", "evidence_ids": ["E1", "E2"]}],
        "conflict_disclosure": {"text": "E1 与 E2 对锁定时长存在冲突，无法确定唯一值。", "evidence_ids": ["E1", "E2"]},
    })
    assert CitationGuard().validate(disclosed, bundle=bundle, project_id=project_id).valid is True
