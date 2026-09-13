from __future__ import annotations

from datetime import datetime
from uuid import UUID

from project_agent.application.services.authorization import (
    DocumentAccessRecord,
    MembershipAccessRecord,
    ProjectAuthorizationRepository,
)


class FakeProjectAuthorizationRepository(ProjectAuthorizationRepository):
    def __init__(self) -> None:
        self.memberships: dict[tuple[UUID, UUID], MembershipAccessRecord] = {}
        self.documents: dict[UUID, list[DocumentAccessRecord]] = {}
        self.knowledge_spaces: dict[UUID, tuple[str, ...]] = {}

    async def get_active_membership(
        self, *, user_id: UUID, project_id: UUID, at: datetime
    ) -> MembershipAccessRecord | None:
        record = self.memberships.get((user_id, project_id))
        if record is None:
            return None
        if at < record.valid_from:
            return None
        if record.valid_to is not None and at >= record.valid_to:
            return None
        return record


    async def list_active_memberships_for_user(
        self, *, user_id: UUID, at: datetime
    ) -> tuple[MembershipAccessRecord, ...]:
        result: list[MembershipAccessRecord] = []
        for (candidate_user_id, _project_id), record in self.memberships.items():
            if candidate_user_id != user_id:
                continue
            if at < record.valid_from:
                continue
            if record.valid_to is not None and at >= record.valid_to:
                continue
            result.append(record)
        return tuple(sorted(result, key=lambda item: item.project_code))

    async def list_published_document_access(
        self, *, project_id: UUID
    ) -> list[DocumentAccessRecord]:
        return list(self.documents.get(project_id, []))

    async def list_active_knowledge_space_ids(self, *, project_id: UUID) -> tuple[str, ...]:
        return self.knowledge_spaces.get(project_id, ())
