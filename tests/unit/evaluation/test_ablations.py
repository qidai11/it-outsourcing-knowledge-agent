from __future__ import annotations

from project_agent.evaluation import ablations
from project_agent.evaluation.models import (
    EvidenceArtifact,
    RetrievalRoundArtifact,
    TrialArtifact,
    TrialClassification,
)


def _trial(
    case_id: str, *, raw=(), governed=(), metadata=None  # type: ignore[no-untyped-def]
) -> TrialArtifact:
    return TrialArtifact(
        case_id=case_id,
        trial_no=1,
        classification=TrialClassification.SCORED,
        business_mode="qa",
        project_code="PRJ-ALPHA",
        user_alias="dev",
        query="q",
        query_sha256="0" * 64,
        retrieval_rounds=tuple(raw),
        final_retrieval_round=raw[-1].round_no if raw else None,
        governed_evidence=tuple(governed),
        metadata=metadata or {},
    )


def _ev(
    doc: str,
    *,
    current: bool,
    lifecycle: str = "PUBLISHED",
    conflict=None,  # type: ignore[no-untyped-def]
) -> EvidenceArtifact:
    return EvidenceArtifact(
        evidence_id=f"e-{doc}",
        doc_code=doc,
        project_code="PRJ-ALPHA",
        document_version_id=f"v-{doc}",
        lifecycle_status=lifecycle,
        is_current=current,
        metadata={} if conflict is None else {"conflict_key": conflict},
    )


def test_pre_governance_shadow_uses_authorized_raw_candidates_only() -> None:
    analyze = getattr(ablations, "analyze_pre_governance_shadow", None)
    assert callable(analyze), "Task 7 pre-governance shadow is not implemented"
    current = _ev("CUR", current=True)
    stale = _ev("OLD", current=False)
    trial = _trial(
        "Q001",
        raw=(RetrievalRoundArtifact(round_no=1, candidates=(current, stale)),),
        governed=(current,),
    )
    result = analyze((trial,), baseline_run_id="base")
    assert result["variant"] == "pre_governance_shadow"
    assert result["mode"] == "shadow"
    assert result["matched_case_ids"] == ["Q001"]
    assert result["diagnostics"]["forbidden_or_noncurrent_candidate_count"] == 1
    assert result["diagnostics"]["candidate_count"] == 2
    assert result["diagnostics"]["governance_changed_case_ids"] == ["Q001"]


def test_pre_governance_conflict_change_ignores_unrelated_governance_filtering() -> None:
    current_conflict = _ev("CUR", current=True, conflict="same-record")
    unrelated_stale = _ev("OLD", current=False)
    trial = _trial(
        "Q001",
        raw=(
            RetrievalRoundArtifact(
                round_no=1,
                candidates=(current_conflict, unrelated_stale),
            ),
        ),
        governed=(current_conflict,),
    )

    result = ablations.analyze_pre_governance_shadow((trial,), baseline_run_id="base")

    assert result["diagnostics"]["governance_changed_case_ids"] == ["Q001"]
    assert result["diagnostics"]["conflict_resolution_changed_case_ids"] == []


def test_pre_guard_shadow_uses_first_and_final_guard_results_without_draft_text() -> None:
    analyze = getattr(ablations, "analyze_pre_guard_shadow", None)
    assert callable(analyze), "Task 7 pre-guard shadow is not implemented"
    trial = _trial(
        "Q001",
        metadata={
            "answer_draft_present": True,
            "citation_guard_history": [
                {"valid": False, "coverage": 0.5},
                {"valid": True, "coverage": 1.0},
            ],
        },
    )
    result = analyze((trial,), baseline_run_id="base")
    assert result["variant"] == "pre_guard_shadow"
    assert result["diagnostics"]["first_draft_already_valid_rate"] == 0.0
    assert result["diagnostics"]["revision_needed_rate"] == 1.0
    assert result["diagnostics"]["counterfactual_invalid_output_rate"] == 1.0
    assert result["diagnostics"]["final_pass_count"] == 1
    assert "answer_text" not in str(result)


def test_ablation_delta_uses_matched_case_population_only() -> None:
    match = getattr(ablations, "match_case_population", None)
    assert callable(match), "Task 7 matched-population logic is not implemented"
    baseline = (_trial("Q001"), _trial("Q002"), _trial("Q003"))
    variant = (_trial("Q002"), _trial("Q003"), _trial("Q004"))
    result = match(baseline, variant)
    assert result["matched_case_ids"] == ["Q002", "Q003"]
    assert result["unavailable_baseline_case_ids"] == ["Q001"]
    assert result["variant_only_case_ids"] == ["Q004"]
    assert result["matched_population"] == 2
