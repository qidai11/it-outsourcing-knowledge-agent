from __future__ import annotations

import pytest

from project_agent.domain.documents import (
    InvalidDocumentTransition,
    can_transition_document,
    transition_document_status,
)
from project_agent.domain.enums import DocumentLifecycleStatus


def test_draft_can_move_to_under_review() -> None:
    assert can_transition_document(
        DocumentLifecycleStatus.DRAFT,
        DocumentLifecycleStatus.UNDER_REVIEW,
    )


def test_published_can_be_superseded() -> None:
    assert can_transition_document(
        DocumentLifecycleStatus.PUBLISHED,
        DocumentLifecycleStatus.SUPERSEDED,
    )


def test_draft_cannot_skip_directly_to_published() -> None:
    assert not can_transition_document(
        DocumentLifecycleStatus.DRAFT,
        DocumentLifecycleStatus.PUBLISHED,
    )


def test_invalid_transition_raises_domain_error() -> None:
    with pytest.raises(InvalidDocumentTransition):
        transition_document_status(
            DocumentLifecycleStatus.DELETE_PENDING,
            DocumentLifecycleStatus.PUBLISHED,
        )


def test_only_published_is_online_retrievable() -> None:
    for status in DocumentLifecycleStatus:
        assert status.is_online_retrievable is (status is DocumentLifecycleStatus.PUBLISHED)
