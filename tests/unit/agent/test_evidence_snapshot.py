from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from uuid import uuid4

import pytest

from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.evidence import GovernedEvidence


def test_governed_evidence_snapshot_hash_is_stable_and_object_is_immutable() -> None:
    item = GovernedEvidence(
        label="E1",
        project_id=uuid4(),
        project_code="PRJ-RETAIL-ALPHA",
        document_version_id=uuid4(),
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        document_title="Requirement",
        version_no=2,
        version_label="v2",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        is_current=True,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        content="same content",
        score=0.9,
        knowledge_space_id="dataset-alpha",
        provider_ref="chunk-1",
        page_no=1,
        section="3.2.1",
        provider_metadata={"x": "y"},
        conflict_key=None,
        claim_value=None,
        unresolved_conflict=False,
    )

    assert len(item.content_hash) == 64
    assert item.content_hash == item.content_hash
    with pytest.raises(FrozenInstanceError):
        item.label = "E2"  # type: ignore[misc]
