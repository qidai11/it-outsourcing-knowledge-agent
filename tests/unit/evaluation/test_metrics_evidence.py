from project_agent.evaluation.metrics import calculate_metrics

from ._metrics_support import DATASET, ev, make_gold, trial

METRIC = "evidence_recall_at_10"


def result_for(groups, docs):  # type: ignore[no-untyped-def]
    gold = make_gold(applicable=(METRIC,), expected={"required_evidence_groups": groups})
    return calculate_metrics(
        [trial(candidates=tuple(ev(code, rank=i + 1) for i, code in enumerate(docs)))],
        {gold.case_id: gold}, {},
    ).acceptance_metrics[0]


def test_evidence_group_is_or_within_group() -> None:
    result = result_for([["A", "B"]], ["B"])
    assert result.measured == 1.0


def test_evidence_groups_are_and_across_groups() -> None:
    result = result_for([["A", "B"], ["C"]], ["B"])
    assert result.measured == 0.5


def test_case_recall_is_fraction_of_required_groups() -> None:
    result = result_for([["A"], ["B"], ["C"]], ["A", "C"])
    assert result.measured == 2 / 3


def test_aggregate_recall_is_macro_mean_across_scorable_cases() -> None:
    g1 = make_gold("Q900", applicable=(METRIC,), expected={"required_evidence_groups": [["A"]]})
    g2 = make_gold(
        "Q901",
        applicable=(METRIC,),
        expected={"required_evidence_groups": [["B"], ["C"]]},
    )
    result = calculate_metrics(
        [trial("Q900", candidates=(ev("A"),)), trial("Q901", candidates=(ev("B"),))],
        {"Q900": g1, "Q901": g2}, {},
    ).acceptance_metrics[0]
    assert result.measured == 0.75
    assert result.denominator == 2


def test_case_with_zero_required_groups_not_in_denominator() -> None:
    g1 = make_gold("Q900", applicable=(METRIC,), expected={"required_evidence_groups": []})
    g2 = make_gold("Q901", applicable=(METRIC,), expected={"required_evidence_groups": [["A"]]})
    result = calculate_metrics(
        [trial("Q900"), trial("Q901", candidates=(ev("A"),))],
        {"Q900": g1, "Q901": g2}, {},
    ).acceptance_metrics[0]
    assert result.denominator == 1
    assert result.case_ids == ("Q901",)


def test_b7_evidence_population_is_exactly_twenty_seven_cases() -> None:
    assert sum(METRIC in g.metric_applicability for g in DATASET.gold_by_case.values()) == 27
