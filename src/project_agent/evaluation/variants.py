"""Controlled WS8 evaluation variants with safety invariants outside the toggle surface."""
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from project_agent.agent.nodes.analyze_query import QueryAnalysis
from project_agent.agent.nodes.resolve_identifiers import (
    ExactResolutionResult,
    IdentifierResolution,
)
from project_agent.domain.identifiers import IdentifierType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from project_agent.application.ports.llm import StructuredLLMPort, StructuredLLMUsagePort
    from project_agent.application.ports.run_graph import RunGraphExecutor
    from project_agent.config import Settings
    from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
    from project_agent.runtime.qa import QARuntimeComposition


class AblationVariant(StrEnum):
    NO_EXACT_REGISTRY = "no_exact_registry"
    SINGLE_ROUND_ONLY = "single_round_only"
    PRE_GOVERNANCE_SHADOW = "pre_governance_shadow"
    PRE_GUARD_SHADOW = "pre_guard_shadow"


SUPPORTED_ABLATION_NAMES = tuple(item.value for item in AblationVariant)
LIVE_ABLATION_NAMES = frozenset(
    {AblationVariant.NO_EXACT_REGISTRY.value, AblationVariant.SINGLE_ROUND_ONLY.value}
)
SHADOW_ABLATION_NAMES = frozenset(
    {AblationVariant.PRE_GOVERNANCE_SHADOW.value, AblationVariant.PRE_GUARD_SHADOW.value}
)


def validate_ablation_name(value: str) -> AblationVariant:
    try:
        return AblationVariant(value)
    except ValueError as exc:
        raise ValueError(f"unsupported ablation: {value}") from exc


class NoExactRegistryResolver:
    """Trace observed exact IDs but remove only Registry-derived document narrowing."""

    async def resolve(
        self,
        *,
        project_id: UUID,
        analysis: QueryAnalysis,
        allowed_document_version_ids: tuple[UUID, ...],
    ) -> ExactResolutionResult:
        del project_id, allowed_document_version_ids
        resolutions = tuple(
            IdentifierResolution(
                identifier_type=item.identifier_type,
                raw_value=item.raw_value,
                normalized_value=item.normalized_value,
                authorized_document_version_ids=(),
                unique_authorized_hit=False,
            )
            for item in analysis.exact_identifiers
            if item.identifier_type is not IdentifierType.PROJECT_CODE
        )
        return ExactResolutionResult(
            resolutions=resolutions,
            constrained_document_version_ids=(),
        )


def qa_runtime_composition_for_variant(value: str) -> QARuntimeComposition:
    """Return only the two frozen live composition overrides.

    The import is lazy so shadow analysis has no runtime/provider dependency.
    """
    variant = validate_ablation_name(value)
    if variant.value in SHADOW_ABLATION_NAMES:
        raise ValueError(f"shadow ablation has no live runtime: {variant.value}")
    from project_agent.runtime.qa import QARuntimeComposition

    if variant is AblationVariant.NO_EXACT_REGISTRY:
        return QARuntimeComposition(
            exact_resolver_factory=lambda _registry: NoExactRegistryResolver()
        )
    return QARuntimeComposition(allow_second_round=False)


def build_controlled_variant_qa_executor(
    *,
    variant: str,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    saver: object,
    knowledge: RagflowAdapter,
    llm: StructuredLLMPort,
    llm_usage: StructuredLLMUsagePort,
) -> RunGraphExecutor:
    """Construct a controlled QA executor without environment-driven ablation flags."""
    from project_agent.runtime.qa import build_production_qa_executor

    return build_production_qa_executor(
        settings=settings,
        session_factory=session_factory,
        saver=saver,
        knowledge=knowledge,
        llm=llm,
        llm_usage=llm_usage,
        composition=qa_runtime_composition_for_variant(variant),
    )
