from __future__ import annotations

from uuid import UUID

from project_agent.domain.identifiers import (
    ExtractedIdentifier,
    IdentifierRegistryEntry,
    IdentifierSpellingSuggestion,
    IdentifierType,
)


class FakeIdentifierRegistryRepository:
    def __init__(self) -> None:
        self.entries: list[IdentifierRegistryEntry] = []
        self.exact_calls: list[tuple[UUID, IdentifierType, str]] = []

    async def replace_for_document_version(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        document_version_id: UUID,
        identifiers: tuple[ExtractedIdentifier, ...],
    ) -> tuple[IdentifierRegistryEntry, ...]:
        raise NotImplementedError

    async def find_exact(
        self,
        *,
        project_id: UUID,
        identifier_type: IdentifierType,
        normalized_value: str,
    ) -> tuple[IdentifierRegistryEntry, ...]:
        self.exact_calls.append((project_id, identifier_type, normalized_value))
        return tuple(
            item
            for item in self.entries
            if item.project_id == project_id
            and item.identifier_type is identifier_type
            and item.normalized_value == normalized_value
        )

    async def suggest(
        self,
        *,
        project_id: UUID,
        identifier_type: IdentifierType,
        normalized_value: str,
        limit: int,
        threshold: float,
    ) -> tuple[IdentifierSpellingSuggestion, ...]:
        return ()
