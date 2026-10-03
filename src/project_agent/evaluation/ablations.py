"""Deterministic WS8 safety-safe ablation analysis over raw evaluation artifacts."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING, Any

from project_agent.evaluation.models import EvidenceArtifact, TrialArtifact

if TYPE_CHECKING:
    from project_agent.evaluation.dataset import EvaluationDataset


def _stable_evidence_key(item: EvidenceArtifact) -> tuple[str, str]:
    return (item.document_version_id or "", item.doc_code or "")


def _final_candidates(trial: TrialArtifact) -> tuple[EvidenceArtifact, ...]:
    if not trial.retrieval_rounds:
        return ()
    round_no = trial.final_retrieval_round
    if round_no is None:
        return trial.retrieval_rounds[-1].candidates
    for item in trial.retrieval_rounds:
        if item.round_no == round_no:
            return item.candidates
    return ()


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def analyze_pre_governance_shadow(
    trials: Sequence[TrialArtifact], *, baseline_run_id: str
) -> dict[str, Any]:
    matched = sorted(item.case_id for item in trials if item.retrieval_rounds)
    candidate_count = 0
    forbidden = 0
    before_current_cases = 0
    after_current_cases = 0
    changed: list[str] = []
    conflict_changed: list[str] = []
    for trial in sorted(trials, key=lambda item: item.case_id):
        if not trial.retrieval_rounds:
            continue
        candidates = _final_candidates(trial)
        governed = trial.governed_evidence
        candidate_count += len(candidates)
        forbidden += sum(
            1
            for item in candidates
            if item.lifecycle_status != "PUBLISHED" or item.is_current is not True
        )
        if any(
            item.lifecycle_status == "PUBLISHED" and item.is_current is True
            for item in candidates
        ):
            before_current_cases += 1
        if any(
            item.lifecycle_status == "PUBLISHED" and item.is_current is True
            for item in governed
        ):
            after_current_cases += 1
        before_keys = {_stable_evidence_key(item) for item in candidates}
        after_keys = {_stable_evidence_key(item) for item in governed}
        if before_keys != after_keys:
            changed.append(trial.case_id)
        conflict_keys = sorted(
            {
                str(item.metadata.get("conflict_key"))
                for item in candidates
                if item.metadata.get("conflict_key") not in (None, "")
            }
        )
        for conflict_key in conflict_keys:
            before_conflict = {
                _stable_evidence_key(item)
                for item in candidates
                if str(item.metadata.get("conflict_key")) == conflict_key
            }
            after_conflict = {
                _stable_evidence_key(item)
                for item in governed
                if str(item.metadata.get("conflict_key")) == conflict_key
            }
            if before_conflict != after_conflict:
                conflict_changed.append(trial.case_id)
                break
    population = len(matched)
    return {
        "variant": "pre_governance_shadow",
        "mode": "shadow",
        "status": "COMPLETE",
        "baseline_evaluation_run_id": baseline_run_id,
        "matched_case_ids": matched,
        "matched_population": population,
        "unavailable_case_ids": sorted(
            item.case_id for item in trials if not item.retrieval_rounds
        ),
        "claim_scope": (
            "diagnostic shadow counterfactual; no causal claim beyond the controlled change"
        ),
        "diagnostics": {
            "candidate_count": candidate_count,
            "forbidden_or_noncurrent_candidate_count": forbidden,
            "forbidden_or_noncurrent_candidate_rate": _rate(forbidden, candidate_count),
            "current_version_hit_before": {
                "numerator": before_current_cases,
                "denominator": population,
                "rate": _rate(before_current_cases, population),
            },
            "current_version_hit_after": {
                "numerator": after_current_cases,
                "denominator": population,
                "rate": _rate(after_current_cases, population),
            },
            "conflict_resolution_changed_case_ids": sorted(conflict_changed),
            "conflict_resolution_changed_case_count": len(conflict_changed),
            "governance_changed_case_ids": sorted(changed),
            "governance_changed_case_count": len(changed),
        },
    }


def _guard_history(trial: TrialArtifact) -> list[dict[str, Any]]:
    raw = trial.metadata.get("citation_guard_history")
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]
    legacy = trial.metadata.get("citation_guard")
    return [dict(legacy)] if isinstance(legacy, dict) else []


def analyze_pre_guard_shadow(
    trials: Sequence[TrialArtifact], *, baseline_run_id: str
) -> dict[str, Any]:
    comparable: list[tuple[TrialArtifact, list[dict[str, Any]]]] = []
    for trial in sorted(trials, key=lambda item: item.case_id):
        history = _guard_history(trial)
        if trial.metadata.get("answer_draft_present") is True and history:
            comparable.append((trial, history))
    population = len(comparable)
    first_valid = sum(1 for _, history in comparable if history[0].get("valid") is True)
    revision_needed = sum(1 for _, history in comparable if history[0].get("valid") is False)
    final_pass = sum(1 for _, history in comparable if history[-1].get("valid") is True)
    final_refusal = sum(
        1
        for trial, history in comparable
        if history[-1].get("valid") is False or trial.refusal_reason is not None
    )
    return {
        "variant": "pre_guard_shadow",
        "mode": "shadow",
        "status": "COMPLETE",
        "baseline_evaluation_run_id": baseline_run_id,
        "matched_case_ids": [trial.case_id for trial, _ in comparable],
        "matched_population": population,
        "unavailable_case_ids": sorted(
            item.case_id for item in trials
            if item.case_id not in {trial.case_id for trial, _ in comparable}
        ),
        "claim_scope": (
            "diagnostic shadow counterfactual; no causal claim beyond the controlled change"
        ),
        "diagnostics": {
            "first_draft_already_valid_rate": _rate(first_valid, population),
            "revision_needed_rate": _rate(revision_needed, population),
            "counterfactual_invalid_output_rate": _rate(revision_needed, population),
            "first_draft_valid_count": first_valid,
            "revision_needed_count": revision_needed,
            "final_pass_count": final_pass,
            "final_refusal_count": final_refusal,
        },
    }


def match_case_population(
    baseline_trials: Sequence[TrialArtifact], variant_trials: Sequence[TrialArtifact]
) -> dict[str, Any]:
    baseline = {item.case_id for item in baseline_trials}
    variant = {item.case_id for item in variant_trials}
    matched = sorted(baseline & variant)
    return {
        "matched_case_ids": matched,
        "matched_population": len(matched),
        "unavailable_baseline_case_ids": sorted(baseline - variant),
        "variant_only_case_ids": sorted(variant - baseline),
    }


def analyze_shadow_ablation(
    variant: str, trials: Sequence[TrialArtifact], *, baseline_run_id: str
) -> dict[str, Any]:
    """Dispatch one of the two frozen offline counterfactuals."""
    from project_agent.evaluation.variants import AblationVariant, validate_ablation_name

    selected = validate_ablation_name(variant)
    if selected is AblationVariant.PRE_GOVERNANCE_SHADOW:
        return analyze_pre_governance_shadow(trials, baseline_run_id=baseline_run_id)
    if selected is AblationVariant.PRE_GUARD_SHADOW:
        return analyze_pre_guard_shadow(trials, baseline_run_id=baseline_run_id)
    raise ValueError(f"live ablation requires controlled runtime artifacts: {selected.value}")


def _live_variant_manifest(
    variant: str, *, baseline_run_id: str, selected_case_ids: Sequence[str]
) -> dict[str, Any]:
    from project_agent.evaluation.variants import AblationVariant, validate_ablation_name

    selected = validate_ablation_name(variant)
    if selected is AblationVariant.NO_EXACT_REGISTRY:
        changed = {"exact_registry_narrowing": False, "allow_second_round": True}
    elif selected is AblationVariant.SINGLE_ROUND_ONLY:
        changed = {"exact_registry_narrowing": True, "allow_second_round": False}
    else:
        raise ValueError(f"shadow ablation has no live runtime: {selected.value}")
    return {
        "variant": selected.value,
        "mode": "live",
        "baseline_evaluation_run_id": baseline_run_id,
        "selected_case_ids": sorted(selected_case_ids),
        "runtime_overrides": changed,
        "safety_invariants": {
            "acl": "ENFORCED",
            "membership": "ENFORCED",
            "evidence_postfilter": "ENFORCED",
            "cross_project_citation": "FORBIDDEN",
            "confirmation": "ENFORCED",
            "idempotency": "ENFORCED",
            "reconciliation": "ENFORCED",
            "citation_guard": "ENFORCED",
            "evidence_governance": "ENFORCED",
        },
        "status": "READY_FOR_CONTROLLED_RUNTIME",
        "claim_scope": (
            "diagnostic controlled variant; no causal claim beyond the controlled change"
        ),
    }


def _mean(values: Sequence[float | int]) -> float | None:
    return None if not values else float(fmean(values))


def _operational_summary(trials: Sequence[TrialArtifact]) -> dict[str, float | None]:
    count = len(trials)
    refusal_count = sum(
        1 for item in trials if item.refusal_reason is not None or not (item.answer or "").strip()
    )
    return {
        "refusal_rate": None if count == 0 else refusal_count / count,
        "latency_ms_mean": _mean(
            [item.latency_ms for item in trials if item.latency_ms is not None]
        ),
        "tokens_mean": _mean(
            [item.total_tokens for item in trials if item.total_tokens is not None]
        ),
        "retrieval_rounds_mean": _mean([len(item.retrieval_rounds) for item in trials]),
    }


def build_live_ablation_result(
    variant: str,
    baseline_trials: Sequence[TrialArtifact],
    variant_trials: Sequence[TrialArtifact],
    *,
    baseline_run_id: str,
    variant_run_id: str,
    dataset: EvaluationDataset,
) -> dict[str, Any]:
    """Compare one live variant only over exact matched, comparable case IDs."""
    from project_agent.evaluation.metrics import calculate_metrics
    from project_agent.evaluation.models import TrialClassification
    from project_agent.evaluation.variants import AblationVariant, validate_ablation_name

    selected = validate_ablation_name(variant)
    if selected not in {AblationVariant.NO_EXACT_REGISTRY, AblationVariant.SINGLE_ROUND_ONLY}:
        raise ValueError(f"shadow ablation has no live metric delta: {selected.value}")
    baseline_by_id = {item.case_id: item for item in baseline_trials}
    variant_by_id = {item.case_id: item for item in variant_trials}
    common = sorted(set(baseline_by_id) & set(variant_by_id))
    failed = {TrialClassification.INFRA_FAILURE, TrialClassification.RUNNER_FAILURE}
    matched = [
        case_id
        for case_id in common
        if baseline_by_id[case_id].classification not in failed
        and variant_by_id[case_id].classification not in failed
    ]
    unavailable = sorted(set(baseline_by_id) - set(matched))
    base = tuple(baseline_by_id[case_id] for case_id in matched)
    changed = tuple(variant_by_id[case_id] for case_id in matched)
    cases_by_id = {item.case_id: item for item in dataset.cases}
    base_metrics = calculate_metrics(
        base, dataset.gold_by_case, dataset.documents_by_code,
        metric_definition_version=dataset.metric_definition_version, cases_by_id=cases_by_id,
    )
    variant_metrics = calculate_metrics(
        changed, dataset.gold_by_case, dataset.documents_by_code,
        metric_definition_version=dataset.metric_definition_version, cases_by_id=cases_by_id,
    )
    base_by_metric = {item.metric_id: item for item in base_metrics.acceptance_metrics}
    changed_by_metric = {item.metric_id: item for item in variant_metrics.acceptance_metrics}
    metric_ids = ("exact_identifier_hit_at_10", "evidence_recall_at_10")
    deltas: list[dict[str, Any]] = []
    for metric_id in metric_ids:
        left = base_by_metric.get(metric_id)
        right = changed_by_metric.get(metric_id)
        if left is None or right is None:
            continue
        comparable_denominator = left.denominator == right.denominator
        delta = (
            float(right.measured) - float(left.measured)
            if comparable_denominator
            and left.measured is not None
            and right.measured is not None
            else None
        )
        deltas.append(
            {
                "metric_id": metric_id,
                "baseline_measured": left.measured,
                "variant_measured": right.measured,
                "baseline_denominator": left.denominator,
                "variant_denominator": right.denominator,
                "delta": delta,
            }
        )
    base_ops = _operational_summary(base)
    changed_ops = _operational_summary(changed)
    operational_delta: dict[str, float | None] = {}
    for key, baseline_value in base_ops.items():
        variant_value = changed_ops[key]
        operational_delta[key] = (
            variant_value - baseline_value
            if variant_value is not None and baseline_value is not None
            else None
        )
    return {
        "variant": selected.value,
        "mode": "live",
        "status": "COMPLETE",
        "baseline_evaluation_run_id": baseline_run_id,
        "variant_evaluation_run_id": variant_run_id,
        "matched_case_ids": matched,
        "matched_population": len(matched),
        "unavailable_case_ids": unavailable,
        "variant_only_case_ids": sorted(set(variant_by_id) - set(baseline_by_id)),
        "metric_deltas": deltas,
        "operational": {
            "baseline": base_ops,
            "variant": changed_ops,
            "delta": operational_delta,
        },
        "claim_scope": (
            "diagnostic controlled variant; no causal claim beyond the controlled change"
        ),
    }


def run_ablation(
    artifact_dir: Path, dataset_root: Path, variant: str
) -> dict[str, Any]:
    """Create a deterministic Task 7 ablation artifact without implicit provider calls.

    Shadow variants are computed immediately from baseline raw artifacts. Live variants
    emit the exact controlled-composition manifest consumed by the later live gate; this
    Task 7 command deliberately never sends hidden provider requests.
    """
    from project_agent.evaluation.artifacts import ArtifactStore
    from project_agent.evaluation.dataset import load_evaluation_dataset
    from project_agent.evaluation.report import load_saved_run
    from project_agent.evaluation.variants import (
        LIVE_ABLATION_NAMES,
        SHADOW_ABLATION_NAMES,
        validate_ablation_name,
    )

    artifact_dir = Path(artifact_dir).resolve()
    dataset_root = Path(dataset_root).resolve()
    selected = validate_ablation_name(variant)
    manifest, trials = load_saved_run(artifact_dir)
    dataset = load_evaluation_dataset(dataset_root)
    if manifest.dataset_version != dataset.dataset_version:
        raise ValueError("baseline dataset version does not match frozen dataset")
    if tuple(sorted(manifest.selected_case_ids)) != tuple(
        sorted(item.case_id for item in trials)
    ):
        raise ValueError("baseline selected case population is incomplete")

    store = ArtifactStore(artifact_dir.parent, artifact_dir.name)
    variant_dir = store.ablations_dir / selected.value
    if selected.value in SHADOW_ABLATION_NAMES:
        payload = analyze_shadow_ablation(
            selected.value, trials, baseline_run_id=manifest.evaluation_run_id
        )
        path = variant_dir / "ablation.json"
        store.write_json(path, payload)
        return {
            "variant": selected.value,
            "mode": "shadow",
            "artifact_path": str(path),
            "matched_population": payload["matched_population"],
            "requires_live_runtime": False,
        }
    if selected.value in LIVE_ABLATION_NAMES:
        payload = _live_variant_manifest(
            selected.value,
            baseline_run_id=manifest.evaluation_run_id,
            selected_case_ids=manifest.selected_case_ids,
        )
        path = variant_dir / "variant-manifest.json"
        store.write_json(path, payload)
        return {
            "variant": selected.value,
            "mode": "live",
            "artifact_path": str(path),
            "variant_artifact_dir": str(variant_dir),
            "requires_live_runtime": True,
        }
    raise AssertionError("validated ablation variant is not classified")
