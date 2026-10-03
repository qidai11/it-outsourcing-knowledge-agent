"""WS8 Task 6 result-claim guardrails."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_agent.evaluation.claims import validate_report_claims
from project_agent.evaluation.models import TrialClassification
from tests.unit.evaluation._metrics_support import trial
from tests.unit.evaluation.test_report import _artifact_dir, _run_report


def test_report_labels_dataset_as_synthetic_v0(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    report, markdown = _run_report(artifact_dir)
    identity = report["evaluation_identity"]
    assert identity["evaluation_label"] == "Synthetic V0 evaluation"
    assert identity["data_provenance"] == "synthetic"
    assert "Synthetic V0 evaluation" in markdown


def test_report_separates_target_from_measured(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    report, markdown = _run_report(artifact_dir)
    metric = report["acceptance"][0]
    assert metric["target"] == ">= 0.95"
    assert metric["measured"] == 0.0
    assert metric["target"] != metric["measured"]
    assert "| Target | Measured |" in markdown


def test_report_does_not_claim_production_accuracy(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    report, markdown = _run_report(artifact_dir)
    rendered = json.dumps(report, ensure_ascii=False) + markdown
    assert "production accuracy" not in rendered.casefold()
    assert "customer projects achieved" not in rendered.casefold()


def test_report_does_not_insert_historical_example_as_measured_value(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(
        tmp_path,
        trial("Q001"),
        metadata={"historical_example_accuracy": 0.97654321},
    )
    report, markdown = _run_report(artifact_dir)
    rendered = json.dumps(report, ensure_ascii=False) + markdown
    assert "historical_example_accuracy" not in rendered
    assert "0.97654321" not in rendered
    assert report["acceptance"][0]["measured"] == 0.0


def test_metric_without_denominator_is_unscorable_not_zero_percent_pass(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(
        tmp_path,
        trial("Q001", classification=TrialClassification.INFRA_FAILURE),
    )
    report, _ = _run_report(artifact_dir)
    for metric in report["acceptance"]:
        assert metric["denominator"] == 0
        assert metric["measured"] is None
        assert metric["status"] == "UNSCORABLE"


def test_infra_failure_is_not_converted_to_model_failure_or_pass(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(
        tmp_path,
        trial("Q001", classification=TrialClassification.INFRA_FAILURE),
    )
    report, _ = _run_report(artifact_dir)
    assert report["coverage"]["infra_failure"] == 1
    assert report["pipeline_status"]["status"] == "FAILED"
    assert report["unscorable_cases"][0]["classification"] == "INFRA_FAILURE"
    assert all(metric["status"] != "PASS" for metric in report["acceptance"])


def test_product_fail_remains_fail_while_pipeline_can_be_complete(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    report, _ = _run_report(artifact_dir)
    assert report["pipeline_status"]["status"] == "COMPLETE"
    assert report["product_status"]["status"] == "FAIL"
    assert any(metric["status"] == "FAIL" for metric in report["acceptance"])


def test_claim_guard_rejects_forbidden_claim_in_report_json(tmp_path: Path) -> None:
    artifact_dir = _artifact_dir(tmp_path, trial("Q001"))
    report, markdown = _run_report(artifact_dir)
    report["claim_limitations"] = ["Production accuracy is 99%."]

    with pytest.raises(ValueError, match="forbidden report claim"):
        validate_report_claims(report, markdown)
