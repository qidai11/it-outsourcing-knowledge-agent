"""Deterministic offline scoring and report generation for WS8 Synthetic V0."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from project_agent.evaluation.artifacts import ArtifactStore
from project_agent.evaluation.claims import (
    CLAIM_LIMITATIONS,
    SYNTHETIC_EVALUATION_LABEL,
    pipeline_status,
    product_status,
    validate_report_claims,
)
from project_agent.evaluation.dataset import EvaluationDataset, load_evaluation_dataset
from project_agent.evaluation.metrics import (
    FROZEN_METRIC_ORDER,
    EvaluationMetrics,
    MetricResult,
    calculate_metrics,
)
from project_agent.evaluation.models import (
    CitationArtifact,
    EvaluationRunManifest,
    EvidenceArtifact,
    IssueArtifact,
    MetricStatus,
    RetrievalRoundArtifact,
    TrialArtifact,
    TrialClassification,
)
from project_agent.evaluation.scoring import CaseBehaviorResult
from project_agent.evaluation.variants import SUPPORTED_ABLATION_NAMES

_SAFETY_METRICS = frozenset(
    {
        "cross_project_evidence",
        "unconfirmed_issue_creation",
        "duplicate_issue_side_effects",
        "critical_regression",
    }
)
_QUALITY_METRICS = frozenset(
    {
        "exact_identifier_hit_at_10",
        "evidence_recall_at_10",
        "current_version_hit_rate",
        "citation_id_validity",
        "no_answer_refusal_accuracy",
    }
)


def _read_object(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected JSON object: {path}")
    return cast(dict[str, Any], raw)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected integer artifact field")
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected numeric artifact field")
    return float(value)


def _string_mapping(value: object) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("expected artifact object field")
    if not all(isinstance(key, str) for key in value):
        raise ValueError("artifact object keys must be strings")
    return cast(dict[str, Any], value)


def _evidence(raw: Mapping[str, Any]) -> EvidenceArtifact:
    return EvidenceArtifact(
        evidence_id=str(raw["evidence_id"]),
        doc_code=_optional_str(raw.get("doc_code")),
        project_code=_optional_str(raw.get("project_code")),
        rank=_optional_int(raw.get("rank")),
        document_version_id=_optional_str(raw.get("document_version_id")),
        lifecycle_status=_optional_str(raw.get("lifecycle_status")),
        is_current=(bool(raw["is_current"]) if raw.get("is_current") is not None else None),
        metadata=_string_mapping(raw.get("metadata")),
    )


def _retrieval_round(raw: Mapping[str, Any]) -> RetrievalRoundArtifact:
    candidates_raw = raw.get("candidates", [])
    if not isinstance(candidates_raw, list):
        raise ValueError("retrieval candidates must be a list")
    return RetrievalRoundArtifact(
        round_no=int(raw["round_no"]),
        candidates=tuple(_evidence(_string_mapping(item)) for item in candidates_raw),
    )


def _citation(raw: Mapping[str, Any]) -> CitationArtifact:
    return CitationArtifact(
        citation_id=str(raw["citation_id"]),
        evidence_id=str(raw["evidence_id"]),
        claim_id=_optional_str(raw.get("claim_id")),
        doc_code=_optional_str(raw.get("doc_code")),
        metadata=_string_mapping(raw.get("metadata")),
    )


def _issue(raw: object) -> IssueArtifact | None:
    if raw is None:
        return None
    item = _string_mapping(raw)
    return IssueArtifact(
        issue_key=_optional_str(item.get("issue_key")),
        request_id=_optional_str(item.get("request_id")),
        status=_optional_str(item.get("status")),
        draft_present=(
            bool(item["draft_present"]) if item.get("draft_present") is not None else None
        ),
        confirmation_state=_optional_str(item.get("confirmation_state")),
        side_effect_count_before=_optional_int(item.get("side_effect_count_before")),
        side_effect_count_after=_optional_int(item.get("side_effect_count_after")),
        reconciliation_outcome=_optional_str(item.get("reconciliation_outcome")),
        metadata=_string_mapping(item.get("metadata")),
    )


def _trial(raw: Mapping[str, Any]) -> TrialArtifact:
    rounds_raw = raw.get("retrieval_rounds", [])
    citations_raw = raw.get("citations", [])
    governed_raw = raw.get("governed_evidence", [])
    for values, label in (
        (rounds_raw, "retrieval_rounds"),
        (citations_raw, "citations"),
        (governed_raw, "governed_evidence"),
    ):
        if not isinstance(values, list):
            raise ValueError(f"{label} must be a list")
    return TrialArtifact(
        case_id=str(raw["case_id"]),
        trial_no=int(raw["trial_no"]),
        classification=TrialClassification(str(raw["classification"])),
        business_mode=str(raw["business_mode"]),
        project_code=str(raw["project_code"]),
        user_alias=str(raw["user_alias"]),
        query=str(raw["query"]),
        query_sha256=str(raw["query_sha256"]),
        http_status=_optional_int(raw.get("http_status")),
        run_id=_optional_str(raw.get("run_id")),
        thread_id=_optional_str(raw.get("thread_id")),
        status_transitions=tuple(str(item) for item in raw.get("status_transitions", [])),
        event_types=tuple(str(item) for item in raw.get("event_types", [])),
        started_at=_optional_str(raw.get("started_at")),
        finished_at=_optional_str(raw.get("finished_at")),
        latency_ms=_optional_float(raw.get("latency_ms")),
        model_alias=_optional_str(raw.get("model_alias")),
        prompt_version=_optional_str(raw.get("prompt_version")),
        prompt_content_hash=_optional_str(raw.get("prompt_content_hash")),
        input_tokens=_optional_int(raw.get("input_tokens")),
        output_tokens=_optional_int(raw.get("output_tokens")),
        total_tokens=_optional_int(raw.get("total_tokens")),
        retrieval_rounds=tuple(
            _retrieval_round(_string_mapping(item)) for item in cast(list[object], rounds_raw)
        ),
        final_retrieval_round=_optional_int(raw.get("final_retrieval_round")),
        governed_evidence=tuple(
            _evidence(_string_mapping(item)) for item in cast(list[object], governed_raw)
        ),
        answer=_optional_str(raw.get("answer")),
        refusal_reason=_optional_str(raw.get("refusal_reason")),
        citations=tuple(
            _citation(_string_mapping(item)) for item in cast(list[object], citations_raw)
        ),
        issue=_issue(raw.get("issue")),
        error_category=_optional_str(raw.get("error_category")),
        metadata=_string_mapping(raw.get("metadata")),
    )


def _manifest(raw: Mapping[str, Any]) -> EvaluationRunManifest:
    return EvaluationRunManifest(
        evaluation_run_id=str(raw["evaluation_run_id"]),
        dataset_version=str(raw["dataset_version"]),
        data_provenance=str(raw["data_provenance"]),
        corpus_version=str(raw["corpus_version"]),
        gold_schema_version=str(raw["gold_schema_version"]),
        metric_definition_version=str(raw["metric_definition_version"]),
        git_commit=str(raw["git_commit"]),
        dirty_worktree=bool(raw["dirty_worktree"]),
        selected_case_ids=tuple(str(item) for item in raw.get("selected_case_ids", [])),
        started_at=_optional_str(raw.get("started_at")),
        python_version=_optional_str(raw.get("python_version")),
        alembic_revision=_optional_str(raw.get("alembic_revision")),
        model_alias=_optional_str(raw.get("model_alias")),
        ragflow_expected_version=_optional_str(raw.get("ragflow_expected_version")),
        ragflow_observed_version=_optional_str(raw.get("ragflow_observed_version")),
        prompt_versions=tuple(str(item) for item in raw.get("prompt_versions", [])),
        prompt_hashes=tuple(str(item) for item in raw.get("prompt_hashes", [])),
        runner_version=_optional_str(raw.get("runner_version")),
        dataset_sha256=_optional_str(raw.get("dataset_sha256")),
        corpus_sha256=_optional_str(raw.get("corpus_sha256")),
        gold_sha256=_optional_str(raw.get("gold_sha256")),
        metadata=_string_mapping(raw.get("metadata")),
    )


def load_saved_run(artifact_dir: Path) -> tuple[EvaluationRunManifest, tuple[TrialArtifact, ...]]:
    """Load exactly one canonical trial for every selected case."""

    artifact_dir = artifact_dir.resolve()
    manifest_path = artifact_dir / "run-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = _manifest(_read_object(manifest_path))
    if manifest.evaluation_run_id != artifact_dir.name:
        raise ValueError("artifact directory name does not match evaluation_run_id")
    if not manifest.selected_case_ids:
        raise ValueError("run manifest contains no selected cases")

    trials: list[TrialArtifact] = []
    for case_id in manifest.selected_case_ids:
        case_dir = artifact_dir / "cases" / case_id
        paths = sorted(case_dir.glob("trial-*.json")) if case_dir.is_dir() else []
        if len(paths) != 1:
            raise ValueError(f"selected case {case_id} must have exactly one trial artifact")
        item = _trial(_read_object(paths[0]))
        if item.case_id != case_id or item.trial_no != 1:
            raise ValueError(f"trial artifact identity mismatch for selected case {case_id}")
        trials.append(item)
    return manifest, tuple(trials)


def _validate_dataset(manifest: EvaluationRunManifest, dataset: EvaluationDataset) -> None:
    expected = {
        "dataset_version": dataset.dataset_version,
        "data_provenance": dataset.data_provenance,
        "corpus_version": dataset.corpus_version,
        "gold_schema_version": dataset.gold_schema_version,
        "metric_definition_version": dataset.metric_definition_version,
    }
    for field_name, expected_value in expected.items():
        if getattr(manifest, field_name) != expected_value:
            raise ValueError(f"run manifest {field_name} does not match frozen dataset")
    integrity = dataset.integrity
    hashes = {
        "dataset_sha256": integrity.get("question_catalog_sha256"),
        "corpus_sha256": integrity.get("corpus_sha256"),
        "gold_sha256": integrity.get("gold_manifest_sha256"),
    }
    for field_name, expected_hash in hashes.items():
        observed = getattr(manifest, field_name)
        if observed is not None and expected_hash is not None and observed != str(expected_hash):
            raise ValueError(f"run manifest {field_name} does not match frozen dataset")
    unknown = sorted(set(manifest.selected_case_ids).difference(dataset.gold_by_case))
    if unknown:
        raise ValueError(f"run manifest contains unknown case IDs: {', '.join(unknown)}")


def _store_for(artifact_dir: Path) -> ArtifactStore:
    path = artifact_dir.resolve()
    return ArtifactStore(path.parent, path.name)


def _metrics_artifact_payload(
    manifest: EvaluationRunManifest, metrics: EvaluationMetrics
) -> dict[str, Any]:
    """Attach frozen-run provenance to the pure Task 5 metric result."""

    return {
        "evaluation_run_id": manifest.evaluation_run_id,
        "dataset_version": manifest.dataset_version,
        "data_provenance": manifest.data_provenance,
        "corpus_version": manifest.corpus_version,
        "gold_schema_version": manifest.gold_schema_version,
        "metric_definition_version": metrics.metric_definition_version,
        "git_commit": manifest.git_commit,
        "dirty_worktree": manifest.dirty_worktree,
        "model_alias": manifest.model_alias,
        "prompt_versions": manifest.prompt_versions,
        "prompt_hashes": manifest.prompt_hashes,
        "ragflow_expected_version": manifest.ragflow_expected_version,
        "ragflow_observed_version": manifest.ragflow_observed_version,
        "dataset_sha256": manifest.dataset_sha256,
        "corpus_sha256": manifest.corpus_sha256,
        "gold_sha256": manifest.gold_sha256,
        "coverage": metrics.coverage,
        "acceptance_metrics": metrics.acceptance_metrics,
        "diagnostic_metrics": metrics.diagnostic_metrics,
        "case_behavior_results": metrics.case_behavior_results,
    }


def score_artifact_directory(artifact_dir: Path, dataset_root: Path) -> EvaluationMetrics:
    """Replay Task 5 scoring from saved artifacts with no live runtime dependencies."""

    manifest, trials = load_saved_run(artifact_dir)
    dataset = load_evaluation_dataset(dataset_root)
    _validate_dataset(manifest, dataset)
    cases_by_id = {item.case_id: item for item in dataset.cases}
    metrics = calculate_metrics(
        trials,
        dataset.gold_by_case,
        dataset.documents_by_code,
        metric_definition_version=manifest.metric_definition_version,
        cases_by_id=cases_by_id,
    )
    store = _store_for(artifact_dir)
    store.write_json(store.metrics_path, _metrics_artifact_payload(manifest, metrics))
    return metrics


def _metric_payload(item: MetricResult) -> dict[str, Any]:
    return {
        "metric_id": item.metric_id,
        "target": item.target,
        "measured": item.measured,
        "numerator": item.numerator,
        "denominator": item.denominator,
        "status": item.status.value,
        "case_ids": list(item.case_ids),
        "notes": list(item.notes),
    }


def _ordered_metric_payloads(metrics: EvaluationMetrics) -> list[dict[str, Any]]:
    index = {metric_id: position for position, metric_id in enumerate(FROZEN_METRIC_ORDER)}
    ordered = sorted(metrics.acceptance_metrics, key=lambda item: index[item.metric_id])
    return [_metric_payload(item) for item in ordered]


def _coverage(metrics: EvaluationMetrics) -> dict[str, int]:
    diagnostics = metrics.diagnostic_metrics.get("coverage", {})
    diagnostic_coverage = diagnostics if isinstance(diagnostics, Mapping) else {}
    return {
        "selected": int(metrics.coverage.get("selected", 0)),
        "scored": int(metrics.coverage.get("scored", 0)),
        "scorable": int(diagnostic_coverage.get("scorable", 0)),
        "unscorable": int(diagnostic_coverage.get("unscorable", 0)),
        "unscorable_gold": int(metrics.coverage.get("unscorable_gold", 0)),
        "unscorable_runtime_scope": int(
            metrics.coverage.get("unscorable_runtime_scope", 0)
        ),
        "infra_failure": int(metrics.coverage.get("infra_failure", 0)),
        "runner_failure": int(metrics.coverage.get("runner_failure", 0)),
    }


def _behavior_by_case(metrics: EvaluationMetrics) -> dict[str, CaseBehaviorResult]:
    return {item.case_id: item for item in metrics.case_behavior_results}


def _case_failures(
    metrics: EvaluationMetrics, trials: Sequence[TrialArtifact], artifact_dir: Path
) -> list[dict[str, Any]]:
    behavior = _behavior_by_case(metrics)
    result: list[dict[str, Any]] = []
    for item in sorted(trials, key=lambda value: value.case_id):
        scored = behavior[item.case_id]
        if scored.status is not MetricStatus.FAIL:
            continue
        failed = [
            {
                "assertion_id": assertion.assertion_id,
                "expected": assertion.expected,
                "observed": assertion.observed,
                "note": assertion.note,
            }
            for assertion in scored.assertions
            if not assertion.passed
        ]
        result.append(
            {
                "case_id": item.case_id,
                "classification": item.classification.value,
                "failed_assertions": failed,
                "raw_artifact_path": str(
                    (artifact_dir / "cases" / item.case_id / "trial-001.json").relative_to(
                        artifact_dir
                    )
                ),
            }
        )
    return result


def _unscorable_cases(
    metrics: EvaluationMetrics,
    trials: Sequence[TrialArtifact],
    dataset: EvaluationDataset,
    artifact_dir: Path,
) -> list[dict[str, Any]]:
    behavior = _behavior_by_case(metrics)
    result: list[dict[str, Any]] = []
    for item in sorted(trials, key=lambda value: value.case_id):
        gold = dataset.gold_for(item.case_id)
        case_behavior = behavior[item.case_id]
        if (
            item.classification is TrialClassification.SCORED
            and gold.scoring.status.value == "SCORABLE"
            and case_behavior.status is not MetricStatus.UNSCORABLE
        ):
            continue
        if gold.scoring.reason:
            reason = gold.scoring.reason
        elif item.error_category:
            reason = item.error_category
        elif case_behavior.notes:
            reason = "; ".join(case_behavior.notes)
        else:
            reason = item.classification.value
        result.append(
            {
                "case_id": item.case_id,
                "classification": item.classification.value,
                "gold_scoring_status": gold.scoring.status.value,
                "reason": reason,
                "benchmark_finding_code": gold.scoring.benchmark_finding_code,
                "raw_artifact_path": str(
                    (artifact_dir / "cases" / item.case_id / "trial-001.json").relative_to(
                        artifact_dir
                    )
                ),
            }
        )
    return result


def _load_ablation_artifacts(artifact_dir: Path) -> list[dict[str, Any]]:
    """Load only frozen Task 7 ablation artifacts in stable variant order."""

    root = artifact_dir / "ablations"
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for variant in SUPPORTED_ABLATION_NAMES:
        variant_dir = root / variant
        if not variant_dir.is_dir():
            continue
        path = variant_dir / "ablation.json"
        if not path.is_file():
            path = variant_dir / "variant-manifest.json"
        if not path.is_file():
            continue
        payload = _read_object(path)
        if payload.get("variant") != variant:
            raise ValueError(f"ablation artifact variant mismatch: {variant}")
        baseline = payload.get("baseline_evaluation_run_id")
        if baseline is not None and baseline != artifact_dir.name:
            raise ValueError(f"ablation artifact baseline mismatch: {variant}")
        result.append(payload)
    return result


def build_report(
    manifest: EvaluationRunManifest,
    metrics: EvaluationMetrics,
    trials: Sequence[TrialArtifact],
    dataset: EvaluationDataset,
    artifact_dir: Path,
) -> dict[str, Any]:
    """Build the complete deterministic Task 6 report model."""

    acceptance = _ordered_metric_payloads(metrics)
    return {
        "evaluation_identity": {
            "evaluation_label": SYNTHETIC_EVALUATION_LABEL,
            "evaluation_run_id": manifest.evaluation_run_id,
            "git_commit": manifest.git_commit,
            "dirty_worktree": manifest.dirty_worktree,
            "dataset_version": manifest.dataset_version,
            "data_provenance": manifest.data_provenance,
            "corpus_version": manifest.corpus_version,
            "gold_schema_version": manifest.gold_schema_version,
            "metric_definition_version": manifest.metric_definition_version,
            "dataset_sha256": manifest.dataset_sha256,
            "corpus_sha256": manifest.corpus_sha256,
            "gold_sha256": manifest.gold_sha256,
        },
        "environment": {
            "started_at": manifest.started_at,
            "python_version": manifest.python_version,
            "alembic_revision": manifest.alembic_revision,
            "model_alias": manifest.model_alias,
            "prompt_versions": list(manifest.prompt_versions),
            "prompt_hashes": list(manifest.prompt_hashes),
            "ragflow_expected_version": manifest.ragflow_expected_version,
            "ragflow_observed_version": manifest.ragflow_observed_version,
            "runner_version": manifest.runner_version,
        },
        "coverage": _coverage(metrics),
        "acceptance": acceptance,
        "safety": [item for item in acceptance if item["metric_id"] in _SAFETY_METRICS],
        "quality": [item for item in acceptance if item["metric_id"] in _QUALITY_METRICS],
        "case_failures": _case_failures(metrics, trials, artifact_dir),
        "unscorable_cases": _unscorable_cases(metrics, trials, dataset, artifact_dir),
        "ablations": _load_ablation_artifacts(artifact_dir),
        "diagnostics": metrics.diagnostic_metrics,
        "claim_limitations": list(CLAIM_LIMITATIONS),
        "pipeline_status": pipeline_status(metrics),
        "product_status": product_status(metrics),
    }


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _metric_table(metrics: Sequence[Mapping[str, Any]]) -> list[str]:
    rows = [
        "Metric | Target | Measured | Numerator/Denominator | Status | Notes",
        "--- | --- | --- | --- | --- | ---",
    ]
    for item in metrics:
        numerator = item.get("numerator")
        denominator = item.get("denominator")
        ratio = (
            "—"
            if numerator is None or denominator in (None, 0)
            else f"{numerator}/{denominator}"
        )
        notes = item.get("notes")
        note_text = "; ".join(str(value) for value in notes) if isinstance(notes, list) else ""
        rows.append(
            " | ".join(
                (
                    _display(item.get("metric_id")),
                    _display(item.get("target")),
                    _display(item.get("measured")),
                    _display(ratio),
                    _display(item.get("status")),
                    _display(note_text),
                )
            )
        )
    if len(rows) == 2:
        rows.append("— | — | — | — | NOT_APPLICABLE | No selected metric population")
    return rows


def render_report_markdown(report: Mapping[str, Any]) -> str:
    """Render stable Markdown with the exact eleven frozen report sections."""

    identity = cast(Mapping[str, Any], report["evaluation_identity"])
    environment = cast(Mapping[str, Any], report["environment"])
    coverage = cast(Mapping[str, Any], report["coverage"])
    acceptance = cast(list[Mapping[str, Any]], report["acceptance"])
    safety = cast(list[Mapping[str, Any]], report["safety"])
    quality = cast(list[Mapping[str, Any]], report["quality"])
    failures = cast(list[Mapping[str, Any]], report["case_failures"])
    unscorable = cast(list[Mapping[str, Any]], report["unscorable_cases"])
    ablations = cast(list[Mapping[str, Any]], report["ablations"])
    diagnostics = report["diagnostics"]
    limitations = cast(list[str], report["claim_limitations"])
    pipeline = cast(Mapping[str, Any], report["pipeline_status"])
    product = cast(Mapping[str, Any], report["product_status"])

    lines = [
        f"# {SYNTHETIC_EVALUATION_LABEL}",
        "",
        "## 1. Evaluation identity",
        "",
        f"- Evaluation run ID: `{_display(identity.get('evaluation_run_id'))}`",
        f"- Git commit: `{_display(identity.get('git_commit'))}`",
        f"- Dirty worktree: `{_display(identity.get('dirty_worktree'))}`",
        f"- Dataset: `{_display(identity.get('dataset_version'))}` (Synthetic V0)",
        f"- Corpus version: `{_display(identity.get('corpus_version'))}`",
        f"- Gold schema: `{_display(identity.get('gold_schema_version'))}`",
        f"- Metric definition: `{_display(identity.get('metric_definition_version'))}`",
        "",
        "## 2. Environment",
        "",
        f"- Python: `{_display(environment.get('python_version'))}`",
        f"- Alembic: `{_display(environment.get('alembic_revision'))}`",
        f"- Model alias: `{_display(environment.get('model_alias'))}`",
        f"- Prompt versions: `{_display(environment.get('prompt_versions'))}`",
        f"- Prompt hashes: `{_display(environment.get('prompt_hashes'))}`",
        f"- RAGFlow expected: `{_display(environment.get('ragflow_expected_version'))}`",
        f"- RAGFlow observed: `{_display(environment.get('ragflow_observed_version'))}`",
        "",
        "## 3. Coverage",
        "",
        "Field | Count",
        "--- | ---:",
    ]
    for key in (
        "selected",
        "scored",
        "scorable",
        "unscorable",
        "infra_failure",
        "runner_failure",
    ):
        lines.append(f"{key} | {_display(coverage.get(key))}")
    lines.extend(
        [
            "",
            "## 4. V1 acceptance table",
            "",
            f"Pipeline status: **{_display(pipeline.get('status'))}**",
            f"Product status: **{_display(product.get('status'))}**",
            "",
            *_metric_table(acceptance),
            "",
            "## 5. Safety invariants",
            "",
            *_metric_table(safety),
            "",
            "## 6. Quality metrics",
            "",
            *_metric_table(quality),
            "",
            "## 7. Case failures",
            "",
            "Case ID | Classification | Assertion | Expected | Observed | Raw artifact",
            "--- | --- | --- | --- | --- | ---",
        ]
    )
    if failures:
        for item in failures:
            raw_assertions = item.get("failed_assertions", [])
            if not isinstance(raw_assertions, list) or not raw_assertions:
                lines.append(
                    " | ".join(
                        (
                            _display(item.get("case_id")),
                            _display(item.get("classification")),
                            "—",
                            "—",
                            "—",
                            _display(item.get("raw_artifact_path")),
                        )
                    )
                )
                continue
            for assertion in raw_assertions:
                assertion_map = (
                    assertion if isinstance(assertion, Mapping) else {}
                )
                lines.append(
                    " | ".join(
                        (
                            _display(item.get("case_id")),
                            _display(item.get("classification")),
                            _display(assertion_map.get("assertion_id")),
                            _display(assertion_map.get("expected")),
                            _display(assertion_map.get("observed")),
                            _display(item.get("raw_artifact_path")),
                        )
                    )
                )
    else:
        lines.append("— | — | — | — | — | No deterministic case-behavior failures")
    lines.extend(
        [
            "",
            "## 8. Unscorable cases",
            "",
            "Case ID | Classification | Reason | Raw artifact",
            "--- | --- | --- | ---",
        ]
    )
    if unscorable:
        for item in unscorable:
            lines.append(
                " | ".join(
                    (
                        _display(item.get("case_id")),
                        _display(item.get("classification")),
                        _display(item.get("reason")),
                        _display(item.get("raw_artifact_path")),
                    )
                )
            )
    else:
        lines.append("— | — | — | No unscorable selected cases")
    lines.extend(
        [
            "",
            "## 9. Ablations",
            "",
            "Baseline | Variant | Mode | Matched population | "
            "Measured delta / counterfactual | Status",
            "--- | --- | --- | ---: | --- | ---",
        ]
    )
    if ablations:
        for item in ablations:
            measured = item.get("metric_deltas", item.get("diagnostics"))
            measured_text = (
                json.dumps(measured, ensure_ascii=False, sort_keys=True, allow_nan=False)
                if isinstance(measured, (Mapping, list))
                else "—"
            )
            lines.append(
                " | ".join(
                    (
                        _display(item.get("baseline_evaluation_run_id")),
                        _display(item.get("variant")),
                        _display(item.get("mode")),
                        _display(item.get("matched_population")),
                        _display(measured_text),
                        _display(item.get("status")),
                    )
                )
            )
    else:
        lines.append("— | — | — | — | — | No Task 7 ablation artifacts")
    lines.extend(
        [
            "",
            "## 10. Operational diagnostics",
            "",
            "```json",
            json.dumps(diagnostics, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False),
            "```",
            "",
            "## 11. Claim limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in limitations)
    return "\n".join(lines) + "\n"


def report_artifact_directory(
    artifact_dir: Path, dataset_root: Path
) -> tuple[dict[str, Any], str]:
    """Score saved raw artifacts and emit deterministic JSON + Markdown reports."""

    artifact_dir = artifact_dir.resolve()
    manifest, trials = load_saved_run(artifact_dir)
    dataset = load_evaluation_dataset(dataset_root)
    _validate_dataset(manifest, dataset)
    metrics = score_artifact_directory(artifact_dir, dataset_root)
    report = build_report(manifest, metrics, trials, dataset, artifact_dir)
    markdown = render_report_markdown(report)
    validate_report_claims(report, markdown)
    store = _store_for(artifact_dir)
    store.write_json(store.report_json_path, report)
    store.report_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    store.report_markdown_path.write_text(markdown, encoding="utf-8", newline="\n")
    return report, markdown
