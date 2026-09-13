from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.domain.identifiers import (
    ExtractedIdentifier,
    IdentifierRegistryEntry,
    IdentifierSpellingSuggestion,
    IdentifierType,
    ManualIdentifier,
    normalize_identifier,
)


class IdentifierRegistryRepository(Protocol):
    async def replace_for_document_version(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        document_version_id: UUID,
        identifiers: Iterable[ExtractedIdentifier],
    ) -> tuple[IdentifierRegistryEntry, ...]: ...

    async def find_exact(
        self,
        *,
        project_id: UUID,
        identifier_type: IdentifierType,
        normalized_value: str,
    ) -> tuple[IdentifierRegistryEntry, ...]: ...

    async def suggest(
        self,
        *,
        project_id: UUID,
        identifier_type: IdentifierType,
        normalized_value: str,
        limit: int,
        threshold: float,
    ) -> tuple[IdentifierSpellingSuggestion, ...]: ...


class IdentifierRegistryService:
    """Application service for deterministic identifier indexing and lookup."""

    def __init__(
        self,
        repository: IdentifierRegistryRepository,
        extractor: IdentifierExtractor,
    ) -> None:
        self._repository = repository
        self._extractor = extractor

    async def index_text(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        document_version_id: UUID,
        text: str,
        manual_identifiers: Iterable[ManualIdentifier] = (),
        manual_override_types: Iterable[IdentifierType] = (),
        page_no: int | None = None,
        section: str | None = None,
    ) -> tuple[IdentifierRegistryEntry, ...]:
        identifiers = self._extractor.extract(
            text,
            manual_identifiers=manual_identifiers,
            manual_override_types=manual_override_types,
            page_no=page_no,
            section=section,
        )
        return await self._repository.replace_for_document_version(
            company_id=company_id,
            project_id=project_id,
            document_version_id=document_version_id,
            identifiers=identifiers,
        )

    async def find_exact(
        self,
        *,
        project_id: UUID,
        identifier_type: IdentifierType,
        value: str,
    ) -> tuple[IdentifierRegistryEntry, ...]:
        normalized = normalize_identifier(identifier_type, value)
        return await self._repository.find_exact(
            project_id=project_id,
            identifier_type=identifier_type,
            normalized_value=normalized,
        )

    async def suggest_spelling(
        self,
        *,
        project_id: UUID,
        identifier_type: IdentifierType,
        value: str,
        limit: int = 5,
        threshold: float = 0.3,
    ) -> tuple[IdentifierSpellingSuggestion, ...]:
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        normalized = normalize_identifier(identifier_type, value)
        return await self._repository.suggest(
            project_id=project_id,
            identifier_type=identifier_type,
            normalized_value=normalized,
            limit=limit,
            threshold=threshold,
        )
