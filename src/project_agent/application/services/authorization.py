from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from project_agent.domain.access import ProjectAccessScope
from project_agent.domain.enums import ProjectRole


class AuthorizationDenied(PermissionError):
    """Raised when a verified identity has no effective project permission."""


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Trusted authentication result.

    Authorization claims deliberately do not live here. Roles, projects and
    document visibility are always reconstructed from the application DB.
    """

    user_id: UUID


@dataclass(frozen=True, slots=True)
class MembershipAccessRecord:
    company_id: UUID
    client_id: UUID
    project_id: UUID
    project_code: str
    role: ProjectRole
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class DocumentAccessRecord:
    document_version_id: UUID
    document_category: str


@dataclass(frozen=True, slots=True)
class AuthorizedProjectContext:
    scope: ProjectAccessScope
    project_code: str
    knowledge_space_ids: tuple[str, ...]


class ProjectAuthorizationRepository(Protocol):
    async def get_active_membership(
        self, *, user_id: UUID, project_id: UUID, at: datetime
    ) -> MembershipAccessRecord | None: ...

    async def list_published_document_access(
        self, *, project_id: UUID
    ) -> list[DocumentAccessRecord]: ...

    async def list_active_knowledge_space_ids(self, *, project_id: UUID) -> tuple[str, ...]: ...

    async def list_active_memberships_for_user(
        self, *, user_id: UUID, at: datetime
    ) -> tuple[MembershipAccessRecord, ...]: ...


class AuthorizationService:
    POLICY_VERSION = "project-membership-v1"

    def __init__(
        self,
        repository: ProjectAuthorizationRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    async def authorize_identity(
        self, *, identity: AuthenticatedIdentity, project_id: UUID
    ) -> AuthorizedProjectContext:
        return await self.authorize_project(user_id=identity.user_id, project_id=project_id)

    async def list_authorized_projects(
        self, *, identity: AuthenticatedIdentity
    ) -> tuple[MembershipAccessRecord, ...]:
        return await self._repository.list_active_memberships_for_user(
            user_id=identity.user_id,
            at=self._clock(),
        )

    async def authorize_project(
        self, *, user_id: UUID, project_id: UUID
    ) -> AuthorizedProjectContext:
        now = self._clock()
        membership = await self._repository.get_active_membership(
            user_id=user_id,
            project_id=project_id,
            at=now,
        )
        if membership is None:
            raise AuthorizationDenied("active project membership is required")

        documents = await self._repository.list_published_document_access(project_id=project_id)
        spaces = await self._repository.list_active_knowledge_space_ids(project_id=project_id)
        version_ids = tuple(sorted((item.document_version_id for item in documents), key=str))
        categories = tuple(sorted({item.document_category for item in documents}))
        scope = ProjectAccessScope(
            company_id=membership.company_id,
            user_id=user_id,
            allowed_client_ids=(membership.client_id,),
            allowed_project_ids=(membership.project_id,),
            allowed_document_version_ids=version_ids,
            allowed_document_categories=categories,
            role_ids=(membership.role.value,),
            max_security_level=0,
            policy_version=self.POLICY_VERSION,
        )
        return AuthorizedProjectContext(
            scope=scope,
            project_code=membership.project_code,
            knowledge_space_ids=tuple(sorted(set(spaces))),
        )
