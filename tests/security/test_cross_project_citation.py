from __future__ import annotations

from uuid import uuid4

from project_agent.application.services.citation_guard import CitationGuard
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.evidence import FrozenEvidence, FrozenEvidenceBundle, GroundedAnswerDraft


def test_cross_project_citation_never_passes_guard() -> None:
    requested_project = uuid4()
    evidence = FrozenEvidence(
        snapshot_id=uuid4(),
        label="E1",
        project_id=uuid4(),
        project_code="PRJ-LOGISTICS-BETA",
        document_version_id=uuid4(),
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        document_title="Foreign Requirement",
        version_no=1,
        version_label="v1",
        authority_level=AuthorityLevel.SIGNED_SCOPE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        is_current=True,
        effective_from=None,
        effective_to=None,
        content="foreign content",
        content_hash="hash",
        score=0.99,
        knowledge_space_id="dataset-beta",
        provider_ref="foreign",
        page_no=None,
        section=None,
        conflict_key=None,
        claim_value=None,
        unresolved_conflict=False,
    )
    draft = GroundedAnswerDraft.model_validate(
        {"claims": [{"text": "foreign", "evidence_ids": ["E1"]}]}
    )

    result = CitationGuard().validate(
        draft,
        bundle=FrozenEvidenceBundle(evidence=(evidence,), unresolved_conflicts={}),
        project_id=requested_project,
    )

    assert result.valid is False
    assert "CROSS_PROJECT_EVIDENCE:E1" in result.errors
