"""WS8 Task 6 deterministic report and offline replay contract."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from project_agent.cli import evaluation
from project_agent.evaluation.artifacts import ArtifactStore
from project_agent.evaluation.models import (
    EvaluationRunManifest,
    TrialArtifact,
    TrialClassification,
)
from tests.unit.evaluation._metrics_support import DATASET, trial

DATASET_ROOT = Path("evaluation/datasets/v0")


def _artifact_dir(
    tmp_path: Path,
    *trials: TrialArtifact,
    metadata: dict[str, object] | None = None,
) -> Path:
    store = ArtifactStore(tmp_path, "eval-task6")
    integrity = DATASET.integrity
    manifest = EvaluationRunManifest(
        evaluation_run_id=store.evaluation_run_id,
        dataset_version=DATASET.dataset_version,
        data_provenance=DATASET.data_provenance,
        corpus_version=DATASET.corpus_version,
        gold_schema_version=DATASET.gold_schema_version,
        metric_definition_version=DATASET.metric_definition_version,
        git_commit="abc123",
        dirty_worktree=True,
        selected_case_ids=tuple(item.case_id for item in trials),
        started_at="2026-09-28T00:00:00+00:00",
        python_version="3.12.14",
        alembic_revision="0005_run_runtime_envelope",
        model_alias="test-model",
        ragflow_expected_version="v0.26.4",
        ragflow_observed_version="v0.26.4",
        prompt_versions=("qa-v1",),
        prompt_hashes=("f" * 64,),
        runner_version="v1",
        dataset_sha256=str(integrity["question_catalog_sha256"]),
        corpus_sha256=str(integrity["corpus_sha256"]),
        gold_sha256=str(integrity["gold_manifest_sha256"]),
        metadata=metadata or {},
    )
    store.write_json(store.run_manifest_path, manifest)
    for item in trials:
        store.write_json(store.trial_path(item.case_id, item.trial_no), item)
    return store.root


def _run_report(artifact_dir: Path) -> tuple[dict[str, object], str]:
    rc = evaluation.main([
        "report",
        "--artifact-dir", str(artifact_dir),
        "--dataset-root", str(DATASET_ROOT),
    ])
    assert rc == 0
    report_json = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    report_md = (artifact_dir / "report.md").read_text(encoding="utf-8")
    return report_json, report_md


def test_same_raw_inputs_produce_identical_report_json(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    _run_report(artifact_dir)
    first = (artifact_dir / "report.json").read_bytes()
    _run_report(artifact_dir)
    second = (artifact_dir / "report.json").read_bytes()
    assert first == second


def test_same_raw_inputs_produce_identical_report_markdown(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    _run_report(artifact_dir)
    first = (artifact_dir / "report.md").read_bytes()
    _run_report(artifact_dir)
    second = (artifact_dir / "report.md").read_bytes()
    assert first == second


def test_report_orders_cases_by_case_id(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q002"), trial("Q001"))
    report, _ = _run_report(artifact_dir)
    failures = report["case_failures"]
    assert isinstance(failures, list)
    assert [item["case_id"] for item in failures] == ["Q001", "Q002"]


def test_report_orders_metrics_by_frozen_metric_order(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q018"), trial("Q001"))
    report, _ = _run_report(artifact_dir)
    acceptance = report["acceptance"]
    assert isinstance(acceptance, list)
    assert [item["metric_id"] for item in acceptance] == [
        "exact_identifier_hit_at_10",
        "evidence_recall_at_10",
        "citation_id_validity",
        "unconfirmed_issue_creation",
    ]


def test_report_contains_selected_scored_and_unscorable_counts(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(
        tmp_path,
        trial("Q001"),
        trial("Q014", classification=TrialClassification.UNSCORABLE_RUNTIME_SCOPE),
    )
    report, _ = _run_report(artifact_dir)
    assert report["coverage"] == {
        "selected": 2,
        "scored": 1,
        "scorable": 1,
        "unscorable": 1,
        "unscorable_gold": 0,
        "unscorable_runtime_scope": 1,
        "infra_failure": 0,
        "runner_failure": 0,
    }


def test_score_writes_required_machine_readable_metrics(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    rc = evaluation.main([
        "score",
        "--artifact-dir", str(artifact_dir),
        "--dataset-root", str(DATASET_ROOT),
    ])
    assert rc == 0
    payload = json.loads((artifact_dir / "metrics.json").read_text(encoding="utf-8"))
    assert {
        "metric_definition_version",
        "coverage",
        "acceptance_metrics",
        "diagnostic_metrics",
        "case_behavior_results",
    } <= set(payload)
    assert payload["dataset_version"] == DATASET.dataset_version
    assert payload["data_provenance"] == "synthetic"
    assert payload["corpus_version"] == DATASET.corpus_version
    assert payload["gold_schema_version"] == DATASET.gold_schema_version
    assert payload["git_commit"] == "abc123"
    assert payload["model_alias"] == "test-model"
    assert payload["prompt_versions"] == ["qa-v1"]
    assert payload["prompt_hashes"] == ["f" * 64]
    assert payload["ragflow_expected_version"] == "v0.26.4"
    assert payload["ragflow_observed_version"] == "v0.26.4"


def test_report_has_exact_required_human_readable_sections(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    _, markdown = _run_report(artifact_dir)
    for heading in (
        "## 1. Evaluation identity",
        "## 2. Environment",
        "## 3. Coverage",
        "## 4. V1 acceptance table",
        "## 5. Safety invariants",
        "## 6. Quality metrics",
        "## 7. Case failures",
        "## 8. Unscorable cases",
        "## 9. Ablations",
        "## 10. Operational diagnostics",
        "## 11. Claim limitations",
    ):
        assert heading in markdown
    assert "Metric | Target | Measured | Numerator/Denominator | Status | Notes" in markdown


def test_score_and_report_replay_perform_no_external_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    artifact_dir = _artifact_dir(
        tmp_path,
        trial("Q014", classification=TrialClassification.UNSCORABLE_RUNTIME_SCOPE),
    )

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("external call attempted")

    monkeypatch.setattr(socket, "create_connection", blocked)
    for command in ("score", "report"):
        assert evaluation.main([
            command,
            "--artifact-dir", str(artifact_dir),
            "--dataset-root", str(DATASET_ROOT),
        ]) == 0


def test_cli_replay_uses_frozen_dataset_without_dataset_root_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The frozen Task 6 CLI shape needs only --artifact-dir, independent of CWD."""
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    assert evaluation.main(["score", "--artifact-dir", str(artifact_dir)]) == 0
    assert evaluation.main(["report", "--artifact-dir", str(artifact_dir)]) == 0


def test_report_markdown_includes_expected_and_observed_failure_facts(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    report, markdown = _run_report(artifact_dir)
    failures = report["case_failures"]
    assert isinstance(failures, list) and failures
    assertions = failures[0]["failed_assertions"]
    assert assertions
    assert "Assertion | Expected | Observed" in markdown
    expected = assertions[0]["expected"]
    observed = assertions[0]["observed"]
    assert ("—" if expected is None else str(expected)) in markdown
    assert ("—" if observed is None else str(observed)) in markdown


def test_unscorable_report_preserves_frozen_reason(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(
        tmp_path,
        trial("Q014", classification=TrialClassification.UNSCORABLE_RUNTIME_SCOPE),
    )
    report, markdown = _run_report(artifact_dir)
    expected_reason = DATASET.gold_for("Q014").scoring.reason
    assert expected_reason
    assert report["unscorable_cases"][0]["reason"] == expected_reason
    assert expected_reason in markdown


def test_report_replays_sorted_ablation_artifacts_without_live_calls(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    store = ArtifactStore(artifact_dir.parent, artifact_dir.name)
    store.write_json(
        store.ablations_dir / "pre_guard_shadow" / "ablation.json",
        {
            "variant": "pre_guard_shadow",
            "mode": "shadow",
            "baseline_evaluation_run_id": artifact_dir.name,
            "matched_case_ids": ["Q001"],
            "matched_population": 1,
            "diagnostics": {"revision_needed_rate": 1.0},
        },
    )
    report, markdown = _run_report(artifact_dir)
    assert [item["variant"] for item in report["ablations"]] == ["pre_guard_shadow"]
    assert report["ablations"][0]["matched_population"] == 1
    assert "pre_guard_shadow" in markdown
    assert "Matched population" in markdown
