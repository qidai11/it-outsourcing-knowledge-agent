from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from project_agent.application.ports.document_repository import DocumentWorkflowRepository
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationDenied,
    AuthorizationService,
    AuthorizedProjectContext,
)
from project_agent.application.use_cases.upload_document import DocumentActor
from project_agent.domain.enums import ProjectRole


class DocumentOperation(StrEnum):
    UPLOAD = "upload_document"
    SUBMIT_REVIEW = "submit_review"
    APPROVE = "approve_document"
    PUBLISH = "publish_document"
    ARCHIVE = "archive_document"


_ROLE_DOCUMENT_PERMISSIONS: dict[ProjectRole, frozenset[str]] = {
    ProjectRole.PROJECT_MANAGER: frozenset(
        {
            DocumentOperation.UPLOAD.value,
            DocumentOperation.SUBMIT_REVIEW.value,
            DocumentOperation.APPROVE.value,
            DocumentOperation.PUBLISH.value,
            DocumentOperation.ARCHIVE.value,
        }
    ),
    ProjectRole.DEVELOPER: frozenset(
        {DocumentOperation.UPLOAD.value, DocumentOperation.SUBMIT_REVIEW.value}
    ),
    ProjectRole.QA: frozenset(
        {DocumentOperation.UPLOAD.value, DocumentOperation.SUBMIT_REVIEW.value}
    ),
    ProjectRole.IMPLEMENTATION: frozenset(
        {DocumentOperation.UPLOAD.value, DocumentOperation.SUBMIT_REVIEW.value}
    ),
    ProjectRole.SUPPORT: frozenset(
        {DocumentOperation.UPLOAD.value, DocumentOperation.SUBMIT_REVIEW.value}
    ),
    ProjectRole.VIEWER: frozenset(),
}


@dataclass(frozen=True, slots=True)
class AuthorizedDocumentActor:
    context: AuthorizedProjectContext
    actor: DocumentActor


class DocumentAccessService:
    def __init__(
        self,
        *,
        authorization: AuthorizationService,
        repository: DocumentWorkflowRepository,
    ) -> None:
        self._authorization = authorization
        self._repository = repository

    async def authorize_project_operation(
        self,
        *,
        identity: AuthenticatedIdentity,
        project_id: UUID,
        operation: DocumentOperation,
        expected_company_id: UUID | None = None,
    ) -> AuthorizedDocumentActor:
        context = await self._authorization.authorize_identity(
            identity=identity,
            project_id=project_id,
        )
        if expected_company_id is not None and context.scope.company_id != expected_company_id:
            raise AuthorizationDenied("membership company does not match requested company")

        if len(context.scope.role_ids) != 1:
            raise AuthorizationDenied("exactly one project role is required")
        try:
            role = ProjectRole(context.scope.role_ids[0])
        except ValueError as exc:
            raise AuthorizationDenied("unknown project role") from exc

        permissions = _ROLE_DOCUMENT_PERMISSIONS[role]
        if operation.value not in permissions:
            raise AuthorizationDenied(f"{operation.value} permission is required")

        return AuthorizedDocumentActor(
            context=context,
            actor=DocumentActor(user_id=identity.user_id, permissions=permissions),
        )

    async def authorize_version_operation(
        self,
        *,
        identity: AuthenticatedIdentity,
        version_id: UUID,
        operation: DocumentOperation,
    ) -> AuthorizedDocumentActor:
        version = await self._repository.get_version(version_id)
        return await self.authorize_project_operation(
            identity=identity,
            project_id=version.project_id,
            operation=operation,
            expected_company_id=version.company_id,
        )
