from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.domain.identifiers import (
    ExtractedIdentifier,
    IdentifierRegistryEntry,
    IdentifierSource,
    IdentifierSpellingSuggestion,
    IdentifierType,
)
from project_agent.infrastructure.db.models.schema import DocumentIdentifierModel


class SqlAlchemyIdentifierRegistryRepository:
    """PostgreSQL-backed exact identifier registry.

    ``find_exact`` uses equality predicates only and maps to the Task 2 B-tree
    index. ``suggest`` is intentionally separate and uses pg_trgm similarity.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_document_version(
        self,
        *,
        company_id: UUID,
        project_id: UUID,
        document_version_id: UUID,
        identifiers: Iterable[ExtractedIdentifier],
    ) -> tuple[IdentifierRegistryEntry, ...]:
        await self._session.execute(
            delete(DocumentIdentifierModel).where(
                DocumentIdentifierModel.document_version_id == document_version_id
            )
        )
        models: list[DocumentIdentifierModel] = []
        for identifier in identifiers:
            model = DocumentIdentifierModel(
                company_id=company_id,
                project_id=project_id,
                document_version_id=document_version_id,
                identifier_type=identifier.identifier_type.value,
                normalized_value=identifier.normalized_value,
                raw_value=identifier.raw_value,
                page_no=identifier.page_no,
                section=identifier.section,
                source=identifier.source.value,
                confidence=(
                    Decimal(str(identifier.confidence))
                    if identifier.confidence is not None
                    else None
                ),
            )
            self._session.add(model)
            models.append(model)
        await self._session.flush()
        return tuple(self._to_entry(model) for model in models)

    async def find_exact(
        self,
        *,
        project_id: UUID,
        identifier_type: IdentifierType,
        normalized_value: str,
    ) -> tuple[IdentifierRegistryEntry, ...]:
        stmt = (
            select(DocumentIdentifierModel)
            .where(
                DocumentIdentifierModel.project_id == project_id,
                DocumentIdentifierModel.identifier_type == identifier_type.value,
                DocumentIdentifierModel.normalized_value == normalized_value,
            )
            .order_by(DocumentIdentifierModel.created_at.asc(), DocumentIdentifierModel.id.asc())
        )
        values = (await self._session.execute(stmt)).scalars().all()
        return tuple(self._to_entry(value) for value in values)

    async def suggest(
        self,
        *,
        project_id: UUID,
        identifier_type: IdentifierType,
        normalized_value: str,
        limit: int,
        threshold: float,
    ) -> tuple[IdentifierSpellingSuggestion, ...]:
        similarity = func.similarity(DocumentIdentifierModel.normalized_value, normalized_value)
        stmt = (
            select(
                DocumentIdentifierModel.normalized_value,
                func.max(similarity).label("similarity"),
            )
            .where(
                DocumentIdentifierModel.project_id == project_id,
                DocumentIdentifierModel.identifier_type == identifier_type.value,
                DocumentIdentifierModel.normalized_value != normalized_value,
                similarity >= threshold,
            )
            .group_by(DocumentIdentifierModel.normalized_value)
            .order_by(desc("similarity"), DocumentIdentifierModel.normalized_value.asc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return tuple(
            IdentifierSpellingSuggestion(
                normalized_value=str(row.normalized_value),
                similarity=float(row.similarity),
            )
            for row in rows
        )

    @staticmethod
    def _to_entry(model: DocumentIdentifierModel) -> IdentifierRegistryEntry:
        return IdentifierRegistryEntry(
            id=model.id,
            company_id=model.company_id,
            project_id=model.project_id,
            document_version_id=model.document_version_id,
            identifier_type=IdentifierType(model.identifier_type),
            normalized_value=model.normalized_value,
            raw_value=model.raw_value,
            source=IdentifierSource(model.source),
            confidence=float(model.confidence) if model.confidence is not None else None,
            page_no=model.page_no,
            section=model.section,
        )
