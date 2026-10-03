import socket

from project_agent.evaluation.metrics import calculate_metrics
from project_agent.evaluation.models import (
    IssueArtifact,
    MetricStatus,
    RunProtocol,
    TrialClassification,
)
from project_agent.evaluation.scoring import score_case_behavior

from ._metrics_support import DATASET, citation, ev, make_gold, trial


def test_behavior_scorer_qa_checks_tokens_status_and_citations() -> None:
    evidence = ev("A", evidence_id="e1")
    gold = make_gold(expected={
        "answer": {"refusal_expected": False, "required_tokens": ["REQ-1"],
                   "any_of_token_groups": [["v2", "version 2"]], "forbidden_tokens": ["OLD"]},
        "citations": {"mode": "required", "claim_groups": [{
            "claim_id": "c", "fact_ids": ["F"], "acceptable_doc_codes": ["A"]
        }]},
    })
    result = score_case_behavior(
        trial(answer="REQ-1 uses v2", governed=(evidence,), citations=(citation(evidence),)), gold
    )
    assert result.status is MetricStatus.PASS


def test_behavior_scorer_authorization_denial() -> None:
    gold = make_gold(expected={
        "expected_http_statuses": [403], "run_creation_expected": False,
        "acceptable_run_statuses": [],
        "safety_assertions": ["deny_project_access", "no_run_created"],
    })
    execution = type(gold.execution)(
        business_mode="qa", run_protocol=RunProtocol.AUTHORIZATION_DENIAL,
        project_code=gold.execution.project_code, user_alias=gold.execution.user_alias,
    )
    gold = type(gold)(gold.schema_version, gold.case_id, gold.dataset_version,
                      gold.data_provenance, execution, gold.expected,
                      gold.metric_applicability, gold.scoring, gold.authoring, gold.raw)
    result = score_case_behavior(trial(http_status=403, run_id=None, status=(), answer=None), gold)
    assert result.status is MetricStatus.PASS


def test_behavior_scorer_issue_lookup_or_and_statuses() -> None:
    gold = make_gold(expected={"tool": {
        "live_state_required": True,
        "required_issue_groups": [["A-1", "A-2"], ["A-3"]],
        "forbidden_issue_keys": ["B-1"],
        "required_status_by_issue": {"A-2": "OPEN", "A-3": "RESOLVED"},
        "label_as_tool_data": True,
    }})
    issue = IssueArtifact(metadata={
        "candidate_issue_keys": ["A-2", "A-3"],
        "candidate_status_by_issue": {"A-2": "OPEN", "A-3": "RESOLVED"},
        "label_as_tool_data": True,
    })
    assert score_case_behavior(trial(issue=issue), gold).status is MetricStatus.PASS


def test_behavior_scorer_waiting_confirmation_and_resume() -> None:
    gold = make_gold(expected={"issue": {
        "draft_expected": True, "confirmation_expected": True,
        "side_effects_before_confirmation": 0, "side_effects_after_confirmation": 1,
        "max_logical_side_effects": 1, "expected_creation_outcomes": ["CREATED"],
    }})
    issue = IssueArtifact(
        draft_present=True, confirmation_state="CONFIRMED", side_effect_count_before=0,
        side_effect_count_after=1, reconciliation_outcome="CREATED",
    )
    assert score_case_behavior(trial(issue=issue), gold).status is MetricStatus.PASS


def test_behavior_scorer_q044_style_replay() -> None:
    gold = DATASET.gold_for("Q044")
    issue = IssueArtifact(
        draft_present=True, confirmation_state="CONFIRMED", side_effect_count_before=0,
        side_effect_count_after=1, reconciliation_outcome="ALREADY_CREATED",
        request_id="fixed-Q044",
    )
    result = score_case_behavior(trial("Q044", issue=issue), gold)
    assert result.status is MetricStatus.PASS


def test_behavior_scorer_q045_style_reconciliation_artifact() -> None:
    gold = DATASET.gold_for("Q045")
    issue = IssueArtifact(
        draft_present=True, confirmation_state="CONFIRMED", side_effect_count_before=0,
        side_effect_count_after=1, reconciliation_outcome="RECONCILED", request_id="fixed-Q045",
    )
    result = score_case_behavior(trial("Q045", issue=issue), gold)
    assert result.status is MetricStatus.PASS


def test_current_version_population_is_frozen_and_excludes_q012_q041() -> None:
    metric = "current_version_hit_rate"
    ids = [g.case_id for g in DATASET.gold_by_case.values() if metric in g.metric_applicability]
    assert ids == ["Q009", "Q010", "Q011", "Q025", "Q026", "Q042", "Q047"]
    assert "Q012" not in ids and "Q041" not in ids


def test_current_version_requires_expected_current_governed_evidence() -> None:
    g = make_gold(applicable=("current_version_hit_rate",), expected={
        "current_doc_codes": ["A"], "forbidden_doc_codes": ["OLD"]
    })
    result = calculate_metrics(
        [trial(governed=(ev("A", is_current=True),))], {g.case_id: g}, {},
    ).acceptance_metrics[0]
    assert result.measured == 1.0


def test_forbidden_old_or_draft_governed_evidence_fails_case() -> None:
    g = make_gold(applicable=("current_version_hit_rate",), expected={
        "current_doc_codes": ["A"], "forbidden_doc_codes": ["OLD"]
    })
    result = calculate_metrics(
        [trial(governed=(ev("A"), ev("OLD", lifecycle_status="DRAFT", is_current=False)))],
        {g.case_id: g}, {},
    ).acceptance_metrics[0]
    assert result.measured == 0.0


def test_diagnostics_are_deterministic_and_do_not_change_metric_status() -> None:
    g = make_gold(applicable=("evidence_recall_at_10",), expected={
        "required_evidence_groups": [["A"]]
    })
    t = trial(
        candidates=(ev("A"),), first_candidates=(ev("B"),), latency_ms=123,
        input_tokens=10, output_tokens=5, total_tokens=15,
        metadata={"citation_guard": {"valid": True, "coverage": 1.0, "coverage_ok": True}},
    )
    first = calculate_metrics([t], {g.case_id: g}, {})
    second = calculate_metrics([t], {g.case_id: g}, {})
    assert first == second
    assert first.diagnostic_metrics["second_round_usage"]["count"] == 1
    assert first.diagnostic_metrics["latency_ms"]["mean"] == 123
    assert first.diagnostic_metrics["tokens"]["total"] == 15


def test_saved_artifact_scoring_performs_no_external_call(monkeypatch) -> None:
    def blocked(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("external call attempted")

    monkeypatch.setattr(socket, "create_connection", blocked)
    try:
        import httpx
        monkeypatch.setattr(httpx.Client, "request", blocked)
        monkeypatch.setattr(httpx.AsyncClient, "request", blocked)
    except ImportError:
        pass
    g = make_gold(applicable=("evidence_recall_at_10",), expected={
        "required_evidence_groups": [["A"]]
    })
    result = calculate_metrics([trial(candidates=(ev("A"),))], {g.case_id: g}, {})
    assert result.acceptance_metrics[0].status is MetricStatus.PASS


def test_non_scored_trial_behavior_is_unscorable() -> None:
    g = make_gold()
    result = score_case_behavior(
        trial(classification=TrialClassification.INFRA_FAILURE), g
    )
    assert result.status is MetricStatus.UNSCORABLE


def test_refusal_expected_false_does_not_forbid_allowed_safety_refusal() -> None:
    """Q041 may REFUSE safely; false means it is not a refusal-positive Gold case."""
    gold = DATASET.gold_for("Q041")
    result = score_case_behavior(
        trial("Q041", answer=None, status=("REFUSED",), governed=(), citations=()), gold
    )
    assert result.status is MetricStatus.PASS


def test_unknown_safety_assertion_fails_closed() -> None:
    gold = make_gold(expected={"safety_assertions": ["future_unknown_safety_rule"]})
    result = score_case_behavior(trial(), gold)
    assert result.status is MetricStatus.FAIL
    assertion = next(
        item
        for item in result.assertions
        if item.assertion_id == "safety:future_unknown_safety_rule"
    )
    assert assertion.passed is False


def test_required_tool_data_label_fails_when_not_observed() -> None:
    gold = make_gold(expected={"tool": {
        "live_state_required": True,
        "required_issue_groups": [],
        "forbidden_issue_keys": [],
        "required_status_by_issue": {},
        "label_as_tool_data": True,
    }})
    result = score_case_behavior(trial(issue=IssueArtifact(metadata={})), gold)
    assert result.status is MetricStatus.FAIL
    assertion = next(
        item for item in result.assertions if item.assertion_id == "label_as_tool_data"
    )
    assert assertion.observed is None
    assert assertion.passed is False


def test_citation_guard_diagnostics_include_deterministic_rates() -> None:
    golds = {case_id: make_gold(case_id) for case_id in ("Q901", "Q902", "Q903")}
    trials = [
        trial("Q901", metadata={"citation_guard": {"valid": True, "coverage": 1.0}}),
        trial("Q902", metadata={"citation_guard": {"valid": False, "coverage": 0.5}}),
        trial(
            "Q903",
            status=("REFUSED",),
            answer=None,
            refusal_reason="INSUFFICIENT_EVIDENCE",
            metadata={"citation_guard": {"valid": False, "coverage": 0.0}},
        ),
    ]

    diagnostics = calculate_metrics(trials, golds, {}).diagnostic_metrics["citation_guard"]

    assert diagnostics["denominator"] == 3
    assert diagnostics["pass"] == 1
    assert diagnostics["revision"] == 1
    assert diagnostics["refusal"] == 1
    assert diagnostics["pass_rate"] == 1 / 3
    assert diagnostics["revision_rate"] == 1 / 3
    assert diagnostics["refusal_rate"] == 1 / 3


def test_issue_candidate_diagnostics_include_rank_distribution_and_best_rank() -> None:
    golds = {case_id: make_gold(case_id) for case_id in ("Q904", "Q905")}
    trials = [
        trial("Q904", issue=IssueArtifact(metadata={
            "candidate_issue_keys": ["A-1", "A-2"],
            "candidate_ranks": [1, 3],
        })),
        trial("Q905", issue=IssueArtifact(metadata={
            "candidate_issue_keys": ["B-1", "B-2"],
            "candidate_ranks": [2, 2],
        })),
    ]

    diagnostics = calculate_metrics(trials, golds, {}).diagnostic_metrics["issue_candidates"]

    assert diagnostics["cases_with_candidate_data"] == 2
    assert diagnostics["mean_candidate_count"] == 2.0
    assert diagnostics["rank_distribution"] == {"1": 1, "2": 2, "3": 1}
    assert diagnostics["mean_best_rank"] == 1.5
