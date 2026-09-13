from __future__ import annotations

from uuid import uuid4

import pytest

from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.application.services.identifier_registry import IdentifierRegistryService
from project_agent.domain.identifiers import (
    IdentifierRegistryEntry,
    IdentifierSpellingSuggestion,
    IdentifierType,
    ManualIdentifier,
)


class FakeIdentifierRepository:
    def __init__(self) -> None:
        self.entries: list[IdentifierRegistryEntry] = []
        self.suggestion_calls = 0

    async def replace_for_document_version(
        self,
        *,
        company_id,
        project_id,
        document_version_id,
        identifiers,
    ) -> tuple[IdentifierRegistryEntry, ...]:
        self.entries = [e for e in self.entries if e.document_version_id != document_version_id]
        for identifier in identifiers:
            self.entries.append(
                IdentifierRegistryEntry(
                    id=uuid4(),
                    company_id=company_id,
                    project_id=project_id,
                    document_version_id=document_version_id,
                    identifier_type=identifier.identifier_type,
                    normalized_value=identifier.normalized_value,
                    raw_value=identifier.raw_value,
                    source=identifier.source,
                    confidence=identifier.confidence,
                    page_no=identifier.page_no,
                    section=identifier.section,
                )
            )
        return tuple(self.entries)

    async def find_exact(self, *, project_id, identifier_type, normalized_value):
        return tuple(
            e
            for e in self.entries
            if e.project_id == project_id
            and e.identifier_type is identifier_type
            and e.normalized_value == normalized_value
        )

    async def suggest(self, *, project_id, identifier_type, normalized_value, limit, threshold):
        self.suggestion_calls += 1
        return (
            IdentifierSpellingSuggestion(normalized_value="REQ-3.2.1", similarity=0.88),
        )


@pytest.mark.asyncio
async def test_exact_lookup_is_project_scoped_and_does_not_call_fuzzy_suggestions() -> None:
    repo = FakeIdentifierRepository()
    service = IdentifierRegistryService(repo, IdentifierExtractor())
    company_id = uuid4()
    alpha = uuid4()
    beta = uuid4()

    await service.index_text(
        company_id=company_id,
        project_id=alpha,
        document_version_id=uuid4(),
        text="REQ-3.2.1",
    )
    await service.index_text(
        company_id=company_id,
        project_id=beta,
        document_version_id=uuid4(),
        text="REQ-3.2.1",
    )

    alpha_hits = await service.find_exact(
        project_id=alpha,
        identifier_type=IdentifierType.REQUIREMENT_ID,
        value="req-3.2.1",
    )

    assert len(alpha_hits) == 1
    assert alpha_hits[0].project_id == alpha
    assert repo.suggestion_calls == 0


@pytest.mark.asyncio
async def test_index_text_applies_manual_override_before_registry_write() -> None:
    repo = FakeIdentifierRepository()
    service = IdentifierRegistryService(repo, IdentifierExtractor())
    version_id = uuid4()
    project_id = uuid4()

    await service.index_text(
        company_id=uuid4(),
        project_id=project_id,
        document_version_id=version_id,
        text="REQ-3.2.1",
        manual_identifiers=(
            ManualIdentifier(
                identifier_type=IdentifierType.REQUIREMENT_ID,
                raw_value="REQ-7.7.7",
            ),
        ),
    )

    old = await service.find_exact(
        project_id=project_id,
        identifier_type=IdentifierType.REQUIREMENT_ID,
        value="REQ-3.2.1",
    )
    new = await service.find_exact(
        project_id=project_id,
        identifier_type=IdentifierType.REQUIREMENT_ID,
        value="REQ-7.7.7",
    )
    assert old == ()
    assert len(new) == 1


@pytest.mark.asyncio
async def test_spelling_suggestion_is_explicitly_separate_from_exact_lookup() -> None:
    repo = FakeIdentifierRepository()
    service = IdentifierRegistryService(repo, IdentifierExtractor())

    suggestions = await service.suggest_spelling(
        project_id=uuid4(),
        identifier_type=IdentifierType.REQUIREMENT_ID,
        value="REQ-3.2.l",
    )

    assert suggestions[0].normalized_value == "REQ-3.2.1"
    assert repo.suggestion_calls == 1
