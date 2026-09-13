from __future__ import annotations

from uuid import UUID

from project_agent.application.services.issue_creation import IssueCreationService


class ReconcileIssueCreateHandler:
    def __init__(self, creation: IssueCreationService) -> None:
        self._creation = creation

    async def __call__(self, aggregate_id: str) -> object:
        return await self._creation.reconcile(UUID(aggregate_id))
