from __future__ import annotations

import os
from typing import Literal
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from project_agent.application.ports.llm import StructuredLLMRequest
from project_agent.infrastructure.llm.adapter import (
    OpenAICompatibleStructuredLLMAdapter,
    StructuredLLMRetryPolicy,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LLM_INTEGRATION") != "1",
    reason="set RUN_LLM_INTEGRATION=1 to run against the real Structured LLM provider",
)


class LiveStructuredProbe(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        pytest.fail(f"{name} is required when RUN_LLM_INTEGRATION=1")
    return value.strip()


@pytest.mark.asyncio
async def test_real_structured_provider_returns_valid_schema_and_usage() -> None:
    base_url = _required_env("LLM_BASE_URL").rstrip("/") + "/"
    api_key = _required_env("LLM_API_KEY")
    model_alias = _required_env("LLM_MODEL_ALIAS")
    timeout = float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "30"))
    max_attempts = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
    request_id = f"ws4-live-probe-{uuid4()}"

    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(
            http,
            api_key=api_key,
            retry_policy=StructuredLLMRetryPolicy(max_attempts=max_attempts),
            request_timeout_seconds=timeout,
        )
        result = await adapter.generate(
            StructuredLLMRequest(
                request_id=request_id,
                model_alias=model_alias,
                system_prompt=(
                    "Return exactly the requested JSON-schema object. "
                    "The only valid semantic result is status=ok."
                ),
                user_prompt="Return status ok.",
                temperature=0.0,
            ),
            LiveStructuredProbe,
        )
        usage = await adapter.get_usage(request_id)

    assert result == LiveStructuredProbe(status="ok")
    assert usage.input_tokens >= 0
    assert usage.output_tokens >= 0
