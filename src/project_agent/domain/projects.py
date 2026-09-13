from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from project_agent.domain.enums import (
    ClientStatus,
    ProjectDeliveryMode,
    ProjectLifecycleStatus,
    ProjectRole,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Client(DomainModel):
    id: UUID
    company_id: UUID
    name: str
    status: ClientStatus = ClientStatus.ACTIVE


class Project(DomainModel):
    id: UUID
    company_id: UUID
    client_id: UUID
    code: str
    name: str
    phase: str
    manager_id: UUID
    delivery_mode: ProjectDeliveryMode = ProjectDeliveryMode.INTERNAL_ONLY
    lifecycle_status: ProjectLifecycleStatus = ProjectLifecycleStatus.ACTIVE


class ProjectMembership(DomainModel):
    project_id: UUID
    user_id: UUID
    role: ProjectRole
    valid_from: datetime
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> ProjectMembership:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        return self

    def is_active_at(self, at: datetime) -> bool:
        if at < self.valid_from:
            return False
        return self.valid_to is None or at < self.valid_to
