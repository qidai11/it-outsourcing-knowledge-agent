from __future__ import annotations

from uuid import uuid4

import pytest

from project_agent.agent.nodes.analyze_query import QueryAnalysisService
from project_agent.agent.nodes.resolve_identifiers import ExactIdentifierResolver
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.application.services.identifier_registry import IdentifierRegistryService
from project_agent.domain.identifiers import (
    IdentifierRegistryEntry,
    IdentifierSource,
    IdentifierType,
)
from tests.fakes.identifiers import FakeIdentifierRegistryRepository


@pytest.mark.asyncio
async def test_unique_authorized_exact_hit_constrains_document_version() -> None:
    project_id = uuid4()
    company_id = uuid4()
    current_version = uuid4()
    old_version = uuid4()
    repo = FakeIdentifierRegistryRepository()
    repo.entries.extend(
        [
            IdentifierRegistryEntry(
                id=uuid4(),
                company_id=company_id,
                project_id=project_id,
                document_version_id=current_version,
                identifier_type=IdentifierType.REQUIREMENT_ID,
                normalized_value="REQ-3.2.1",
                raw_value="REQ-3.2.1",
                source=IdentifierSource.REGEX,
                confidence=1.0,
            ),
            IdentifierRegistryEntry(
                id=uuid4(),
                company_id=company_id,
                project_id=project_id,
                document_version_id=old_version,
                identifier_type=IdentifierType.REQUIREMENT_ID,
                normalized_value="REQ-3.2.1",
                raw_value="REQ-3.2.1",
                source=IdentifierSource.REGEX,
                confidence=1.0,
            ),
        ]
    )
    service = IdentifierRegistryService(repo, IdentifierExtractor())
    resolver = ExactIdentifierResolver(service)
    analysis = QueryAnalysisService(IdentifierExtractor()).analyze("REQ-3.2.1 的验收条件？")

    result = await resolver.resolve(
        project_id=project_id,
        analysis=analysis,
        allowed_document_version_ids=(current_version,),
    )

    assert result.constrained_document_version_ids == (current_version,)
    assert repo.exact_calls == [(project_id, IdentifierType.REQUIREMENT_ID, "REQ-3.2.1")]
