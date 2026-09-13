from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from project_agent.agent.nodes.analyze_query import QueryAnalysis
from project_agent.application.services.identifier_registry import IdentifierRegistryService
from project_agent.domain.identifiers import IdentifierType


class IdentifierResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier_type: IdentifierType
    raw_value: str
    normalized_value: str
    authorized_document_version_ids: tuple[UUID, ...]
    unique_authorized_hit: bool


class ExactResolutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolutions: tuple[IdentifierResolution, ...]
    constrained_document_version_ids: tuple[UUID, ...]


class ExactIdentifierResolver:
    """Resolve deterministic identifiers against the project-scoped Registry first."""

    def __init__(self, registry: IdentifierRegistryService) -> None:
        self._registry = registry

    async def resolve(
        self,
        *,
        project_id: UUID,
        analysis: QueryAnalysis,
        allowed_document_version_ids: tuple[UUID, ...],
    ) -> ExactResolutionResult:
        allowed = set(allowed_document_version_ids)
        resolutions: list[IdentifierResolution] = []
        unique_versions: set[UUID] = set()

        for identifier in analysis.exact_identifiers:
            if identifier.identifier_type is IdentifierType.PROJECT_CODE:
                continue
            hits = await self._registry.find_exact(
                project_id=project_id,
                identifier_type=identifier.identifier_type,
                value=identifier.normalized_value,
            )
            authorized = tuple(
                sorted(
                    {
                        hit.document_version_id
                        for hit in hits
                        if hit.document_version_id in allowed
                    },
                    key=str,
                )
            )
            unique = len(authorized) == 1
            if unique:
                unique_versions.add(authorized[0])
            resolutions.append(
                IdentifierResolution(
                    identifier_type=identifier.identifier_type,
                    raw_value=identifier.raw_value,
                    normalized_value=identifier.normalized_value,
                    authorized_document_version_ids=authorized,
                    unique_authorized_hit=unique,
                )
            )

        return ExactResolutionResult(
            resolutions=tuple(resolutions),
            constrained_document_version_ids=tuple(sorted(unique_versions, key=str)),
        )
