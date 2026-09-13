from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProjectAccessScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_id: UUID
    user_id: UUID
    allowed_client_ids: tuple[UUID, ...] = ()
    allowed_project_ids: tuple[UUID, ...] = ()
    allowed_document_version_ids: tuple[UUID, ...] | None = None
    allowed_document_categories: tuple[str, ...] = ()
    role_ids: tuple[str, ...] = ()
    max_security_level: int = 0
    policy_version: str
