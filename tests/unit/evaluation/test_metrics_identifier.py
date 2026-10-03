from project_agent.evaluation.metrics import calculate_metrics
from project_agent.evaluation.models import MetricStatus

from ._metrics_support import DATASET, ev, make_gold, trial

METRIC = "exact_identifier_hit_at_10"


def metric_for(rank: int, *, project_code: str = "PRJ-ALPHA"):
    gold = make_gold(
        applicable=(METRIC,),
        expected={"identifier_targets": [{
            "identifier_type": "requirement_id",
            "normalized_value": "REQ-1",
            "acceptable_doc_codes": ["A-REQ"],
        }]},
    )
    result = calculate_metrics(
        [trial(candidates=(ev("A-REQ", rank=rank, project_code=project_code),))],
        {gold.case_id: gold}, {},
    )
    return result.acceptance_metrics[0]


def test_identifier_hit_at_rank_10_passes() -> None:
    result = metric_for(10)
    assert result.measured == 1.0
    assert result.status is MetricStatus.PASS


def test_identifier_hit_at_rank_11_fails() -> None:
    result = metric_for(11)
    assert result.measured == 0.0
    assert result.status is MetricStatus.FAIL


def test_same_identifier_cross_project_doc_does_not_pass() -> None:
    result = metric_for(1, project_code="PRJ-BETA")
    assert result.measured == 0.0


def test_identifier_metric_uses_only_gold_applicable_cases() -> None:
    applicable = make_gold(
        "Q900", applicable=(METRIC,), expected={"identifier_targets": [{
            "identifier_type": "requirement_id", "normalized_value": "REQ-1",
            "acceptable_doc_codes": ["A-REQ"],
        }]},
    )
    excluded = make_gold(
        "Q901", expected={"identifier_targets": [{
            "identifier_type": "requirement_id", "normalized_value": "REQ-2",
            "acceptable_doc_codes": ["A-MISS"],
        }]},
    )
    result = calculate_metrics(
        [trial("Q900", candidates=(ev("A-REQ"),)), trial("Q901")],
        {"Q900": applicable, "Q901": excluded}, {},
    ).acceptance_metrics[0]
    assert result.case_ids == ("Q900",)
    assert result.denominator == 1


def test_b7_identifier_population_is_frozen_fourteen_cases_fifteen_targets() -> None:
    golds = [g for g in DATASET.gold_by_case.values() if METRIC in g.metric_applicability]
    assert len(golds) == 14
    assert sum(len(g.expected["identifier_targets"]) for g in golds) == 15
