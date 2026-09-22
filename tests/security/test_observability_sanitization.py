from __future__ import annotations

import json

import httpx
import pytest

from project_agent.infrastructure.ragflow.client import RagflowHttpClient, RagflowRetryPolicy
from project_agent.infrastructure.ragflow.errors import RagflowHttpError
from project_agent.observability.logging import (
    bind_log_context,
    clear_log_context,
    configure_structured_logging,
    get_logger,
)
from project_agent.observability.metrics import (
    ObservabilityMetrics,
    metrics_context,
)
from project_agent.observability.sanitization import safe_error_fields

SENTINELS = {
    "jwt": "JWT-SENTINEL-99321",
    "ragflow_api_key": "RAGFLOW-KEY-SENTINEL-44218",
    "llm_api_key": "LLM-KEY-SENTINEL-77103",
    "password": "PASSWORD-SENTINEL-81644",
    "query": "QUERY-SENTINEL-20953",
    "evidence": "EVIDENCE-SENTINEL-54197",
    "answer": "ANSWER-SENTINEL-73510",
    "system_prompt": "SYSTEM-PROMPT-SENTINEL-10422",
    "user_prompt": "USER-PROMPT-SENTINEL-60817",
    "provider_body": "PROVIDER-BODY-SENTINEL-33804",
    "issue_key": "ISSUE-KEY-SENTINEL-44001",
    "document_id": "DOCUMENT-ID-SENTINEL-55002",
    "user_id": "USER-ID-SENTINEL-66003",
    "run_id": "RUN-ID-SENTINEL-77004",
}


class _ProviderError(RuntimeError):
    status_code = 503
    code = "rate_limit"


def test_structured_logs_redact_sensitive_content_and_keep_safe_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_structured_logging(log_level="INFO")
    clear_log_context()
    bind_log_context(run_id=SENTINELS["run_id"], user_id=SENTINELS["user_id"])

    exc = _ProviderError(SENTINELS["provider_body"])
    get_logger().error(
        "provider_failed",
        outcome="error",
        duration_ms=12.5,
        authorization=f"Bearer {SENTINELS['jwt']}",
        ragflow_api_key=SENTINELS["ragflow_api_key"],
        llm_api_key=SENTINELS["llm_api_key"],
        password=SENTINELS["password"],
        query=SENTINELS["query"],
        evidence=SENTINELS["evidence"],
        answer=SENTINELS["answer"],
        system_prompt=SENTINELS["system_prompt"],
        user_prompt=SENTINELS["user_prompt"],
        provider_error_body=SENTINELS["provider_body"],
        **safe_error_fields(exc),
    )

    payload = json.loads(capsys.readouterr().out.strip())
    serialized = json.dumps(payload, sort_keys=True)

    for key in (
        "jwt",
        "ragflow_api_key",
        "llm_api_key",
        "password",
        "query",
        "evidence",
        "answer",
        "system_prompt",
        "user_prompt",
        "provider_body",
    ):
        assert SENTINELS[key] not in serialized

    assert payload["event"] == "provider_failed"
    assert payload["outcome"] == "error"
    assert payload["duration_ms"] == 12.5
    assert payload["error_type"] == "_ProviderError"
    assert payload["status_code"] == 503
    assert payload["error_code"] == "rate_limit"
    assert payload["run_id"] == SENTINELS["run_id"]
    assert payload["user_id"] == SENTINELS["user_id"]

    clear_log_context()


@pytest.mark.asyncio
async def test_provider_failure_log_omits_raw_ragflow_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_structured_logging(log_level="INFO")
    clear_log_context()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            400,
            json={"code": 400, "message": SENTINELS["provider_body"]},
        )

    metrics = ObservabilityMetrics()
    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = RagflowHttpClient(
            http,
            api_key=SENTINELS["ragflow_api_key"],
            retry_policy=RagflowRetryPolicy(max_attempts=1),
        )
        with metrics_context(metrics), pytest.raises(RagflowHttpError):
            await client.request_data("GET", "/api/v1/datasets")

    payload = json.loads(capsys.readouterr().out.strip())
    serialized = json.dumps(payload, sort_keys=True)
    rendered = metrics.render_latest().decode()

    assert payload["event"] == "ragflow_request_failed"
    assert payload["provider"] == "ragflow"
    assert payload["operation"] == "dataset_list"
    assert payload["outcome"] == "error"
    assert payload["error_type"] == "RagflowHttpError"
    assert payload["status_code"] == 400
    assert SENTINELS["provider_body"] not in serialized
    assert SENTINELS["ragflow_api_key"] not in serialized
    assert SENTINELS["provider_body"] not in rendered
    assert SENTINELS["ragflow_api_key"] not in rendered


def test_prometheus_output_excludes_dynamic_identifier_sentinels() -> None:
    metrics = ObservabilityMetrics()
    metrics.observe_http(
        method="GET",
        route="/api/v1/runs/{run_id}",
        status_code=200,
        duration_seconds=0.01,
    )
    metrics.observe_run(business_mode="qa", outcome="succeeded", duration_seconds=0.2)
    metrics.observe_queue_claim(job_type="EXECUTE_AGENT_RUN", age_seconds=0.3)
    metrics.observe_queue_completion(job_type="EXECUTE_AGENT_RUN")
    metrics.observe_queue_failure(job_type="EXECUTE_AGENT_RUN", outcome="retry")
    metrics.observe_queue_reaped(job_type="EXECUTE_AGENT_RUN", outcome="failed")
    metrics.increment_retrieval_round()
    metrics.observe_ragflow(operation="retrieve", outcome="success", duration_seconds=0.1)
    metrics.observe_llm_request(
        model_alias="configured-model", outcome="success", duration_seconds=0.1
    )
    metrics.observe_llm_tokens(model_alias="configured-model", input_tokens=10, output_tokens=4)
    metrics.observe_citation(outcome="pass")
    metrics.observe_authorization_denial(reason="scope_mismatch")
    metrics.observe_issue_confirmation(outcome="confirmed")
    metrics.observe_issue_create(outcome="created")

    rendered = metrics.render_latest().decode()

    for key in ("issue_key", "document_id", "user_id", "run_id"):
        assert SENTINELS[key] not in rendered

    for forbidden_label in (
        "run_id=",
        "job_id=",
        "user_id=",
        "project_id=",
        "issue_key=",
        "document_id=",
    ):
        assert forbidden_label not in rendered

    assert 'route="/api/v1/runs/{run_id}"' in rendered
    assert 'operation="retrieve",outcome="success"' in rendered
    assert 'reason="scope_mismatch"' in rendered
