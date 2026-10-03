from __future__ import annotations

from uuid import uuid4

import pytest

from project_agent.agent.nodes.analyze_query import QueryAnalysisService
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.evaluation import variants


def test_supported_ablation_names_are_exactly_the_frozen_four() -> None:
    assert getattr(variants, "SUPPORTED_ABLATION_NAMES", None) == (
        "no_exact_registry",
        "single_round_only",
        "pre_governance_shadow",
        "pre_guard_shadow",
    )


@pytest.mark.parametrize(
    "name",
    (
        "acl_off",
        "membership_off",
        "postfilter_off",
        "cross_project_citation_allowed",
        "confirmation_off",
        "idempotency_off",
        "reconciliation_off",
    ),
)
def test_forbidden_security_toggle_fails_before_runtime_construction(name: str) -> None:
    validate = getattr(variants, "validate_ablation_name", None)
    assert callable(validate), "Task 7 ablation validation is not implemented"
    with pytest.raises(ValueError, match="unsupported ablation"):
        validate(name)


@pytest.mark.asyncio
async def test_no_exact_registry_removes_only_registry_narrowing() -> None:
    resolver_type = getattr(variants, "NoExactRegistryResolver", None)
    assert resolver_type is not None, "Task 7 no_exact_registry resolver is not implemented"
    analysis = QueryAnalysisService(IdentifierExtractor()).analyze(
        "REQ-3.2.1 and /api/v1/runs"
    )
    result = await resolver_type().resolve(
        project_id=uuid4(),
        analysis=analysis,
        allowed_document_version_ids=(uuid4(),),
    )
    assert result.constrained_document_version_ids == ()
    assert tuple(item.normalized_value for item in result.resolutions) == tuple(
        item.normalized_value
        for item in analysis.exact_identifiers
        if item.identifier_type.value != "project_code"
    )
    assert all(not item.authorized_document_version_ids for item in result.resolutions)
    assert all(not item.unique_authorized_hit for item in result.resolutions)


def test_shadow_variants_cannot_construct_live_runtime() -> None:
    factory = getattr(variants, "qa_runtime_composition_for_variant", None)
    assert callable(factory), "Task 7 live-variant composition is not implemented"
    for name in ("pre_governance_shadow", "pre_guard_shadow"):
        with pytest.raises(ValueError, match="shadow"):
            factory(name)


def test_no_exact_registry_keeps_project_scope_and_postfilter() -> None:
    composition = variants.qa_runtime_composition_for_variant("no_exact_registry")
    fields = set(composition.__dataclass_fields__)
    assert fields == {"exact_resolver_factory", "allow_second_round"}
    assert composition.allow_second_round is True
    # Authorization, membership, RAGFlow dataset scope and postfilter are not configurable here.
    for forbidden_field in ("authorization", "membership", "knowledge", "dataset", "postfilter"):
        assert forbidden_field not in fields


def test_single_round_variant_keeps_citation_guard_and_governance() -> None:
    composition = variants.qa_runtime_composition_for_variant("single_round_only")
    assert composition.allow_second_round is False
    fields = set(composition.__dataclass_fields__)
    assert "citation_guard" not in fields
    assert "evidence_governance" not in fields
