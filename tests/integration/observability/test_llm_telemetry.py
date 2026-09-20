from __future__ import annotations

import pytest
from pydantic import BaseModel
from tests.fakes.llm import FakeStructuredLLM

from project_agent.application.ports.llm import StructuredLLMRequest
from project_agent.observability.metrics import (
    ObservabilityMetrics,
    ObservedStructuredLLM,
    metrics_context,
)


class Reply(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_observed_llm_counts_logical_success_and_tokens() -> None:
    fake = FakeStructuredLLM()
    fake.queue_response({"answer": "ok"}, input_tokens=7, output_tokens=3)
    observed = ObservedStructuredLLM(fake, fake)
    metrics = ObservabilityMetrics()
    request = StructuredLLMRequest(
        request_id="req-1",
        model_alias="model-a",
        system_prompt="secret",
        user_prompt="secret",
    )

    with metrics_context(metrics):
        result = await observed.generate(request, Reply)
        usage = await observed.get_usage(request.request_id)

    assert result.answer == "ok"
    assert usage.input_tokens == 7 and usage.output_tokens == 3
    rendered = metrics.render_latest().decode()
    assert (
        'project_agent_llm_requests_total'
        '{model_alias="model-a",outcome="success"} 1.0' in rendered
    )
    assert 'project_agent_llm_tokens_total{direction="input",model_alias="model-a"} 7.0' in rendered
    assert (
        'project_agent_llm_tokens_total'
        '{direction="output",model_alias="model-a"} 3.0' in rendered
    )
    assert (
        'project_agent_llm_tokens_total'
        '{direction="total",model_alias="model-a"} 10.0' in rendered
    )
    assert "secret" not in rendered

@pytest.mark.asyncio
async def test_real_structured_llm_records_usage_when_live_enabled() -> None:
    import os
    from uuid import uuid4

    import httpx

    from project_agent.infrastructure.llm.adapter import (
        OpenAICompatibleStructuredLLMAdapter,
        StructuredLLMRetryPolicy,
    )

    if os.getenv("RUN_LLM_INTEGRATION") != "1":
        pytest.skip("set RUN_LLM_INTEGRATION=1 to run WS6 real LLM telemetry gate")
    base_url = os.environ["LLM_BASE_URL"].rstrip("/") + "/"
    api_key = os.environ["LLM_API_KEY"]
    model_alias = os.environ["LLM_MODEL_ALIAS"]
    timeout = float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "30"))
    max_attempts = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
    request = StructuredLLMRequest(
        request_id=f"ws6-live-{uuid4()}",
        model_alias=model_alias,
        system_prompt="Return the requested JSON object only.",
        user_prompt="Return answer ok.",
    )
    metrics = ObservabilityMetrics()
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(
            http,
            api_key=api_key,
            retry_policy=StructuredLLMRetryPolicy(max_attempts=max_attempts),
            request_timeout_seconds=timeout,
        )
        observed = ObservedStructuredLLM(adapter, adapter)
        with metrics_context(metrics):
            await observed.generate(request, Reply)
            usage = await observed.get_usage(request.request_id)
    rendered = metrics.render_latest().decode()
    assert usage.input_tokens >= 0 and usage.output_tokens >= 0
    assert f'model_alias="{model_alias}",outcome="success"' in rendered
    assert api_key not in rendered
