from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from project_agent.domain.identifiers import IdentifierType
from project_agent.infrastructure.db.models.schema import DocumentIdentifierModel
from project_agent.infrastructure.db.repositories.identifiers import (
    SqlAlchemyIdentifierRegistryRepository,
)


class _ScalarResult:
    def all(self) -> list[object]:
        return []


class _Result:
    def scalars(self) -> _ScalarResult:
        return _ScalarResult()

    def all(self) -> list[object]:
        return []


class _CaptureSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        return _Result()


def _sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect())).lower()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_exact_repository_query_uses_only_equality_predicates() -> None:
    session = _CaptureSession()
    repository = SqlAlchemyIdentifierRegistryRepository(session)  # type: ignore[arg-type]

    await repository.find_exact(
        project_id=uuid4(),
        identifier_type=IdentifierType.REQUIREMENT_ID,
        normalized_value="REQ-3.2.1",
    )

    sql = _sql(session.statements[-1])
    assert "document_identifiers.project_id =" in sql
    assert "document_identifiers.identifier_type =" in sql
    assert "document_identifiers.normalized_value =" in sql
    assert "similarity(" not in sql
    assert "vector" not in sql


@pytest.mark.asyncio
async def test_spelling_repository_query_is_the_only_path_using_similarity() -> None:
    session = _CaptureSession()
    repository = SqlAlchemyIdentifierRegistryRepository(session)  # type: ignore[arg-type]

    await repository.suggest(
        project_id=uuid4(),
        identifier_type=IdentifierType.REQUIREMENT_ID,
        normalized_value="REQ-3.2.L",
        limit=5,
        threshold=0.3,
    )

    sql = _sql(session.statements[-1])
    assert "similarity(" in sql
    assert "document_identifiers.project_id =" in sql
    assert "document_identifiers.identifier_type =" in sql


def test_identifier_table_keeps_btree_and_trigram_indexes_separate() -> None:
    indexes = {index.name: index for index in DocumentIdentifierModel.__table__.indexes}

    exact = indexes["idx_identifier_exact"]
    assert tuple(column.name for column in exact.columns) == (
        "project_id",
        "identifier_type",
        "normalized_value",
    )

    trigram = indexes["idx_identifier_trgm"]
    assert tuple(column.name for column in trigram.columns) == ("normalized_value",)
    assert trigram.dialect_options["postgresql"]["using"] == "gin"
