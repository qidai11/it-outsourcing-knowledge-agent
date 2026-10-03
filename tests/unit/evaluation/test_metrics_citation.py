from project_agent.evaluation.metrics import calculate_metrics
from project_agent.evaluation.models import CitationArtifact

from ._metrics_support import DATASET, citation, ev, make_gold, trial

METRIC = "citation_id_validity"


def gold():
    return make_gold(
        applicable=(METRIC,),
        expected={"citations": {"mode": "required", "claim_groups": [{
            "claim_id": "claim", "fact_ids": ["F1"], "acceptable_doc_codes": ["A"]
        }]}},
    )


def metric(t):  # type: ignore[no-untyped-def]
    g = gold()
    return calculate_metrics([t], {g.case_id: g}, {}).acceptance_metrics[0]


def test_valid_citation_references_same_run_final_governed_evidence() -> None:
    evidence = ev("A", evidence_id="e1")
    result = metric(trial(governed=(evidence,), citations=(citation(evidence),)))
    assert result.measured == 1.0


def test_missing_snapshot_fails() -> None:
    result = metric(trial(citations=(CitationArtifact("c1", "missing", doc_code="A"),)))
    assert result.measured == 0.0


def test_cross_run_snapshot_fails() -> None:
    evidence = ev("A", evidence_id="e1", metadata={"run_id": "other-run"})
    result = metric(trial(governed=(evidence,), citations=(citation(evidence),), run_id="run-1"))
    assert result.measured == 0.0


def test_cross_project_snapshot_fails() -> None:
    evidence = ev("A", evidence_id="e1", project_code="PRJ-BETA")
    result = metric(trial(governed=(evidence,), citations=(citation(evidence),)))
    assert result.measured == 0.0


def test_noncurrent_or_nonpublished_snapshot_fails() -> None:
    old = ev("A", evidence_id="old", is_current=False)
    draft = ev("A", evidence_id="draft", lifecycle_status="DRAFT")
    result = metric(trial(
        governed=(old, draft),
        citations=(citation(old, citation_id="c1"), citation(draft, citation_id="c2")),
    ))
    assert result.measured == 0.0
    assert result.denominator == 2


def test_required_answer_with_zero_citations_is_case_failure() -> None:
    result = metric(trial(answer="supported factual answer", citations=()))
    assert result.measured == 0.0
    assert result.denominator == 1


def test_b7_citation_population_is_exactly_twenty_five_cases() -> None:
    assert sum(METRIC in g.metric_applicability for g in DATASET.gold_by_case.values()) == 25


def test_required_if_answered_refusal_does_not_create_fake_citation_failure() -> None:
    g = make_gold(
        applicable=(METRIC,),
        expected={"citations": {"mode": "required_if_answered", "claim_groups": []}},
    )
    result = calculate_metrics(
        [trial(answer="No supported evidence.", status=("REFUSED",), citations=())],
        {g.case_id: g},
        {},
    ).acceptance_metrics[0]
    assert result.status.value == "UNSCORABLE"
    assert result.denominator == 0
