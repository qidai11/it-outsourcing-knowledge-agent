from project_agent.evaluation.metrics import calculate_metrics

from ._metrics_support import DATASET, make_gold, trial

METRIC = "no_answer_refusal_accuracy"


def gold(case_id="Q900"):  # type: ignore[no-untyped-def]
    return make_gold(
        case_id, applicable=(METRIC,),
        expected={
            "answer": {"refusal_expected": True, "required_tokens": [],
                       "any_of_token_groups": [], "forbidden_tokens": []},
            "acceptable_run_statuses": ["SUCCEEDED", "REFUSED"],
        },
    )


def test_expected_refusal_with_no_supported_answer_passes() -> None:
    g = gold()
    result = calculate_metrics(
        [trial(answer=None, refusal_reason="NO_AUTHORIZED_EVIDENCE", status=("REFUSED",))],
        {g.case_id: g}, {},
    ).acceptance_metrics[0]
    assert result.measured == 1.0


def test_fabricated_supported_looking_answer_fails() -> None:
    g = gold()
    result = calculate_metrics(
        [trial(answer="The answer is definitely 42", refusal_reason=None)], {g.case_id: g}, {},
    ).acceptance_metrics[0]
    assert result.measured == 0.0


def test_authorization_denial_does_not_enter_refusal_denominator() -> None:
    denial = make_gold(
        "Q901", applicable=(METRIC,),
        expected={
            "answer": {"refusal_expected": True, "required_tokens": [],
                       "any_of_token_groups": [], "forbidden_tokens": []},
            "expected_http_statuses": [403], "run_creation_expected": False,
        },
    )
    denial = type(denial)(
        schema_version=denial.schema_version, case_id=denial.case_id,
        dataset_version=denial.dataset_version, data_provenance=denial.data_provenance,
        execution=type(denial.execution)(
            business_mode="qa", run_protocol=__import__(
                "project_agent.evaluation.models", fromlist=["RunProtocol"]
            ).RunProtocol.AUTHORIZATION_DENIAL,
            project_code=denial.execution.project_code, user_alias=denial.execution.user_alias,
        ),
        expected=denial.expected, metric_applicability=denial.metric_applicability,
        scoring=denial.scoring, authoring=denial.authoring, raw=denial.raw,
    )
    result = calculate_metrics(
        [trial("Q901", answer=None, http_status=403, run_id=None, status=())],
        {"Q901": denial}, {},
    ).acceptance_metrics[0]
    assert result.denominator == 0
    assert result.measured is None


def test_population_is_exactly_three_frozen_cases() -> None:
    ids = [g.case_id for g in DATASET.gold_by_case.values() if METRIC in g.metric_applicability]
    assert ids == ["Q013", "Q027", "Q050"]
