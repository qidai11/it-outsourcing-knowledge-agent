from __future__ import annotations

from project_agent.domain.enums import DocumentLifecycleStatus


class InvalidDocumentTransition(ValueError):
    """Raised when a document lifecycle transition violates V1 governance rules."""


_ALLOWED_TRANSITIONS: dict[DocumentLifecycleStatus, frozenset[DocumentLifecycleStatus]] = {
    DocumentLifecycleStatus.DRAFT: frozenset(
        {DocumentLifecycleStatus.UNDER_REVIEW, DocumentLifecycleStatus.DELETE_PENDING}
    ),
    DocumentLifecycleStatus.UNDER_REVIEW: frozenset(
        {
            DocumentLifecycleStatus.DRAFT,
            DocumentLifecycleStatus.APPROVED,
            DocumentLifecycleStatus.DELETE_PENDING,
        }
    ),
    DocumentLifecycleStatus.APPROVED: frozenset(
        {
            DocumentLifecycleStatus.DRAFT,
            DocumentLifecycleStatus.PUBLISHED,
            DocumentLifecycleStatus.DELETE_PENDING,
        }
    ),
    DocumentLifecycleStatus.PUBLISHED: frozenset(
        {
            DocumentLifecycleStatus.SUPERSEDED,
            DocumentLifecycleStatus.ARCHIVED,
            DocumentLifecycleStatus.DELETE_PENDING,
        }
    ),
    DocumentLifecycleStatus.SUPERSEDED: frozenset(
        {DocumentLifecycleStatus.ARCHIVED, DocumentLifecycleStatus.DELETE_PENDING}
    ),
    DocumentLifecycleStatus.ARCHIVED: frozenset({DocumentLifecycleStatus.DELETE_PENDING}),
    DocumentLifecycleStatus.DELETE_PENDING: frozenset({DocumentLifecycleStatus.DELETED}),
    DocumentLifecycleStatus.DELETED: frozenset(),
}


def can_transition_document(
    current: DocumentLifecycleStatus,
    target: DocumentLifecycleStatus,
) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def transition_document_status(
    current: DocumentLifecycleStatus,
    target: DocumentLifecycleStatus,
) -> DocumentLifecycleStatus:
    if not can_transition_document(current, target):
        raise InvalidDocumentTransition(f"document lifecycle transition {current} -> {target} is invalid")
    return target
