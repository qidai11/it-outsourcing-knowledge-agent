from project_agent.evaluation.metrics import calculate_metrics
from project_agent.evaluation.models import IssueArtifact

from ._metrics_support import DATASET, citation, ev, make_gold, trial


def metric(metric_id, t, *, expected=None):  # type: ignore[no-untyped-def]
    g = make_gold(applicable=(metric_id,), expected=expected)
    return calculate_metrics([t], {g.case_id: g}, {}).acceptance_metrics[0]


def test_cross_project_candidate_counts_as_violation() -> None:
    result = metric("cross_project_evidence", trial(
        candidates=(ev("B", project_code="PRJ-BETA"),),
    ))
    assert result.measured == 1


def test_cross_project_governed_evidence_counts_as_violation() -> None:
    result = metric("cross_project_evidence", trial(
        governed=(ev("B", project_code="PRJ-BETA"),),
    ))
    assert result.measured == 1


def test_cross_project_citation_counts_as_violation() -> None:
    evidence = ev("B", project_code="PRJ-BETA", evidence_id="e1")
    result = metric("cross_project_evidence", trial(
        governed=(evidence,), citations=(citation(evidence),),
    ))
    assert result.measured >= 1


def test_unconfirmed_issue_creation_counts_side_effect_before_confirmation() -> None:
    issue = IssueArtifact(side_effect_count_before=1, side_effect_count_after=1)
    result = metric("unconfirmed_issue_creation", trial(issue=issue))
    assert result.measured == 1


def test_duplicate_issue_side_effect_metric_allows_at_most_one_logical_issue() -> None:
    issue = IssueArtifact(side_effect_count_before=0, side_effect_count_after=2)
    result = metric("duplicate_issue_side_effects", trial(issue=issue))
    assert result.measured == 1
    ok = IssueArtifact(side_effect_count_before=0, side_effect_count_after=1)
    assert metric("duplicate_issue_side_effects", trial(issue=ok)).measured == 0


def test_b7_safety_populations_are_frozen() -> None:
    expected = {
        "cross_project_evidence": 9,
        "unconfirmed_issue_creation": 5,
        "duplicate_issue_side_effects": 2,
    }
    for metric_id, count in expected.items():
        actual = sum(
            metric_id in gold.metric_applicability for gold in DATASET.gold_by_case.values()
        )
        assert actual == count
