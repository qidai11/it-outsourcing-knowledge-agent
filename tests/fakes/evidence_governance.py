from __future__ import annotations

from uuid import UUID

from project_agent.application.services.evidence_governance import DocumentEvidenceMetadata


class FakeEvidenceGovernanceRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, DocumentEvidenceMetadata] = {}

    async def get_document_evidence_metadata(
        self, *, document_version_ids: tuple[UUID, ...]
    ) -> dict[UUID, DocumentEvidenceMetadata]:
        return {value: self.records[value] for value in document_version_ids if value in self.records}
