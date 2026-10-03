"""WS8 Task 6 report claim guardrails.

The report layer separates technical pipeline completion from measured product
results and keeps Synthetic V0 language explicit.  These helpers are pure and
must never consult a provider, database, clock, or network service.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from project_agent.evaluation.metrics import EvaluationMetrics
from project_agent.evaluation.models import MetricStatus

SYNTHETIC_EVALUATION_LABEL = "Synthetic V0 evaluation"

CLAIM_LIMITATIONS = (
    "All measured results in this report use the frozen Synthetic V0 benchmark.",
    "These synthetic benchmark measurements do not establish accuracy on production data.",
    "No customer usage or customer-project outcome is measured by this evaluation.",
    "Historical or illustrative numbers are not used as measured values unless reproduced "
    "from this run's raw artifacts.",
)

_FORBIDDEN_PHRASES = (
    "production accuracy",
    "customer projects achieved",
)


def pipeline_status(metrics: EvaluationMetrics) -> dict[str, Any]:
    """Return technical pipeline status without interpreting product quality as pipeline health."""

    coverage = metrics.coverage
    selected = int(coverage.get("selected", 0))
    accounted = sum(
        int(coverage.get(key, 0))
        for key in (
            "scored",
            "unscorable_gold",
            "unscorable_runtime_scope",
            "infra_failure",
            "runner_failure",
        )
    )
    failures = int(coverage.get("infra_failure", 0)) + int(coverage.get("runner_failure", 0))
    complete = selected > 0 and accounted == selected and failures == 0
    notes: list[str] = []
    if selected == 0:
        notes.append("no selected cases")
    if accounted != selected:
        notes.append(f"selected/accounted mismatch: {selected}/{accounted}")
    if failures:
        notes.append(f"infrastructure/runner failures: {failures}")
    return {
        "status": "COMPLETE" if complete else "FAILED",
        "selected": selected,
        "accounted": accounted,
        "failure_count": failures,
        "notes": notes,
    }


def product_status(metrics: EvaluationMetrics) -> dict[str, Any]:
    """Aggregate product metric status while preserving FAIL and UNSCORABLE."""

    statuses = [item.status for item in metrics.acceptance_metrics]
    if MetricStatus.FAIL in statuses:
        status = MetricStatus.FAIL
    elif MetricStatus.UNSCORABLE in statuses:
        status = MetricStatus.UNSCORABLE
    elif MetricStatus.PASS in statuses:
        status = MetricStatus.PASS
    else:
        status = MetricStatus.NOT_APPLICABLE
    return {
        "status": status.value,
        "metric_count": len(statuses),
        "failed_metric_count": sum(item is MetricStatus.FAIL for item in statuses),
        "unscorable_metric_count": sum(item is MetricStatus.UNSCORABLE for item in statuses),
    }


def validate_report_claims(report: Mapping[str, Any], markdown: str) -> None:
    """Fail closed when a generated report violates frozen Task 6 claim rules."""

    identity = report.get("evaluation_identity")
    if not isinstance(identity, Mapping):
        raise ValueError("report evaluation_identity is missing")
    if identity.get("evaluation_label") != SYNTHETIC_EVALUATION_LABEL:
        raise ValueError("report must label the dataset as Synthetic V0 evaluation")
    if identity.get("data_provenance") != "synthetic":
        raise ValueError("Task 6 report only supports frozen Synthetic V0 provenance")

    acceptance = report.get("acceptance")
    if not isinstance(acceptance, Sequence) or isinstance(acceptance, (str, bytes)):
        raise ValueError("report acceptance metrics are missing")
    for raw_metric in acceptance:
        if not isinstance(raw_metric, Mapping):
            raise ValueError("report acceptance entry must be an object")
        if "target" not in raw_metric or "measured" not in raw_metric:
            raise ValueError("report acceptance entry must separate target and measured")
        denominator = raw_metric.get("denominator")
        measured = raw_metric.get("measured")
        status = raw_metric.get("status")
        if denominator in (None, 0) and measured is None and status == MetricStatus.PASS.value:
            raise ValueError("metric without denominator cannot be PASS")

    combined = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" + markdown
    ).casefold()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in combined:
            raise ValueError(f"forbidden report claim: {phrase}")
