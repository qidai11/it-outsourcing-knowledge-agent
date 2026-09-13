from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.domain.identifiers import IdentifierType


class QueryExactIdentifier(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier_type: IdentifierType
    raw_value: str
    normalized_value: str


class QueryAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_query: str
    standalone_query: str
    exact_identifiers: tuple[QueryExactIdentifier, ...]

    @property
    def project_codes(self) -> tuple[str, ...]:
        return tuple(
            item.normalized_value
            for item in self.exact_identifiers
            if item.identifier_type is IdentifierType.PROJECT_CODE
        )


class QueryAnalysisService:
    """Deterministic first-pass analysis that never rewrites exact identifiers."""

    def __init__(self, extractor: IdentifierExtractor) -> None:
        self._extractor = extractor

    def analyze(self, query: str) -> QueryAnalysis:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query cannot be blank")
        extracted = self._extractor.extract(normalized_query)
        exact = tuple(
            QueryExactIdentifier(
                identifier_type=item.identifier_type,
                raw_value=item.raw_value,
                normalized_value=item.normalized_value,
            )
            for item in extracted
        )
        return QueryAnalysis(
            original_query=query,
            standalone_query=normalized_query,
            exact_identifiers=exact,
        )
