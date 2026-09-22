from prometheus_client import generate_latest

from project_agent.observability.metrics import (
    ObservabilityMetrics,
    current_metrics,
    metrics_context,
)


def test_two_metric_instances_have_isolated_registries() -> None:
    left = ObservabilityMetrics()
    right = ObservabilityMetrics()
    left.observe_http(method="GET", route="/health", status_code=200, duration_seconds=0.01)

    expected = (
        b'project_agent_http_requests_total{method="GET",route="/health",'
        b'status_code="200"} 1.0'
    )
    assert expected in generate_latest(left.registry)
    assert expected.split(b" 1.0")[0] not in generate_latest(right.registry)


def test_metric_surface_has_no_dynamic_id_label_names_or_values() -> None:
    metrics = ObservabilityMetrics()
    metrics.observe_run(business_mode="qa", outcome="succeeded", duration_seconds=0.2)
    rendered = metrics.render_latest().decode()

    for forbidden in (
        "run_id=",
        "job_id=",
        "user_id=",
        "project_id=",
        "issue_key=",
        "document_id=",
    ):
        assert forbidden not in rendered


def test_metric_recorders_expose_only_frozen_bounded_dimensions() -> None:
    metrics = ObservabilityMetrics()
    metrics.observe_http(
        method="POST",
        route="/api/v1/runs",
        status_code=202,
        duration_seconds=0.01,
    )
    metrics.observe_run(business_mode="qa", outcome="refused", duration_seconds=0.02)
    metrics.observe_queue_claim(job_type="EXECUTE_AGENT_RUN", age_seconds=1.0)
    metrics.observe_queue_completion(job_type="EXECUTE_AGENT_RUN")
    metrics.observe_queue_failure(job_type="EXECUTE_AGENT_RUN", outcome="retry")
    metrics.observe_queue_reaped(job_type="EXECUTE_AGENT_RUN", outcome="failed", count=2)
    metrics.increment_retrieval_round()
    metrics.observe_ragflow(operation="retrieve", outcome="success", duration_seconds=0.03)
    metrics.observe_llm_request(model_alias="test-model", outcome="success", duration_seconds=0.04)
    metrics.observe_llm_tokens(model_alias="test-model", input_tokens=3, output_tokens=2)
    metrics.observe_citation(outcome="revision")
    metrics.observe_authorization_denial(reason="scope_mismatch")
    metrics.observe_issue_confirmation(outcome="confirmed")
    metrics.observe_issue_create(outcome="pending_reconciliation")

    rendered = metrics.render_latest().decode()
    assert (
        'project_agent_queue_reaped_total{job_type="EXECUTE_AGENT_RUN",outcome="failed"} 2.0'
        in rendered
    )
    assert (
        'project_agent_llm_tokens_total{direction="total",model_alias="test-model"} 5.0'
        in rendered
    )
    assert 'project_agent_citation_guard_total{outcome="revision"} 1.0' in rendered
    assert 'project_agent_authorization_denials_total{reason="scope_mismatch"} 1.0' in rendered


def test_metrics_context_is_scoped_and_restored() -> None:
    metrics = ObservabilityMetrics()
    assert current_metrics() is None

    with metrics_context(metrics):
        assert current_metrics() is metrics

    assert current_metrics() is None
