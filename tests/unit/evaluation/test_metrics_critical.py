from project_agent.evaluation.metrics import calculate_metrics
from project_agent.evaluation.models import MetricStatus, TrialClassification

from ._metrics_support import DATASET, make_gold, trial

METRIC = "critical_regression"


def test_critical_regression_population_is_exactly_15_p0_cases() -> None:
    ids = [g.case_id for g in DATASET.gold_by_case.values() if METRIC in g.metric_applicability]
    priorities = {case.case_id: case.priority for case in DATASET.cases}
    assert len(ids) == 15
    assert all(priorities[case_id] == "P0" for case_id in ids)


def test_p0_case_pass_requires_every_deterministic_assertion() -> None:
    good = make_gold(
        applicable=(METRIC,),
        expected={"answer": {"refusal_expected": False, "required_tokens": ["REQ-1"],
                             "any_of_token_groups": [], "forbidden_tokens": ["BAD"]}},
    )
    passed = calculate_metrics(
        [trial(answer="REQ-1")], {good.case_id: good}, {},
    ).acceptance_metrics[0]
    failed = calculate_metrics(
        [trial(answer="REQ-1 BAD")], {good.case_id: good}, {},
    ).acceptance_metrics[0]
    assert passed.measured == 1.0
    assert failed.measured == 0.0


def test_unscorable_p0_prevents_claim_full_p0_proof() -> None:
    g1 = make_gold("Q900", applicable=(METRIC,))
    g2 = make_gold("Q901", applicable=(METRIC,))
    result = calculate_metrics(
        [trial("Q900"), trial("Q901", classification=TrialClassification.INFRA_FAILURE)],
        {"Q900": g1, "Q901": g2}, {},
    ).acceptance_metrics[0]
    assert result.measured == 1.0
    assert result.status is MetricStatus.UNSCORABLE
    assert any("Q901" in note for note in result.notes)


def test_p0_aggregate_is_passed_scorable_over_scorable_population() -> None:
    g1 = make_gold("Q900", applicable=(METRIC,))
    g2 = make_gold(
        "Q901", applicable=(METRIC,),
        expected={"answer": {"refusal_expected": False, "required_tokens": ["must"],
                             "any_of_token_groups": [], "forbidden_tokens": []}},
    )
    result = calculate_metrics(
        [trial("Q900"), trial("Q901", answer="wrong")],
        {"Q900": g1, "Q901": g2}, {},
    ).acceptance_metrics[0]
    assert result.numerator == 1
    assert result.denominator == 2
    assert result.measured == 0.5
