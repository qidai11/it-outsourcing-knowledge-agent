from __future__ import annotations

import json
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from project_agent.application.ports.llm import LLMTokenUsage, StructuredLLMRequest
from project_agent.infrastructure.llm import (
    OpenAICompatibleStructuredLLMAdapter,
    StructuredLLMHTTPError,
    StructuredLLMProtocolError,
    StructuredLLMRetryPolicy,
    StructuredLLMSchemaError,
    StructuredLLMTransportError,
)


class RouteDecision(BaseModel):
    route: Literal["knowledge", "issue"]


def _request() -> StructuredLLMRequest:
    return StructuredLLMRequest(
        request_id="llm-1",
        model_alias="test-model",
        system_prompt="Return one valid route.",
        user_prompt="How do I deploy?",
        temperature=0.0,
    )


def _success_response(*, content: str = '{"route":"knowledge"}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        },
    )


@pytest.mark.asyncio
async def test_structured_http_adapter_validates_json_schema_and_records_usage() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _success_response()

    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(
            http,
            api_key="secret-test-key",
            retry_policy=StructuredLLMRetryPolicy(max_attempts=1),
        )
        result = await adapter.generate(_request(), RouteDecision)

    assert result == RouteDecision(route="knowledge")
    assert await adapter.get_usage("llm-1") == LLMTokenUsage(11, 3)
    outbound = captured[0]
    body = json.loads(outbound.content)
    assert outbound.url == httpx.URL("https://llm.example.test/v1/chat/completions")
    assert body["model"] == "test-model"
    assert body["temperature"] == 0.0
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == RouteDecision.model_json_schema()
    assert outbound.headers["Authorization"] == "Bearer secret-test-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("not-json", "structured response"),
        ('{"route":"unsupported"}', "structured response"),
    ],
)
async def test_structured_http_adapter_rejects_invalid_structured_content(
    content: str, match: str
) -> None:
    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(lambda request: _success_response(content=content)),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(http, api_key="secret")
        with pytest.raises(StructuredLLMSchemaError, match=match):
            await adapter.generate(_request(), RouteDecision)


@pytest.mark.asyncio
async def test_structured_http_adapter_rejects_missing_content_as_protocol_error() -> None:
    response = httpx.Response(
        200,
        json={
            "choices": [{"message": {}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        },
    )
    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(lambda request: response),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(http, api_key="secret")
        with pytest.raises(StructuredLLMProtocolError, match="provider response shape"):
            await adapter.generate(_request(), RouteDecision)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"prompt_tokens": "11", "completion_tokens": 3},
        {"prompt_tokens": 11, "completion_tokens": -1},
    ],
)
async def test_structured_http_adapter_requires_valid_usage(usage: dict[str, object]) -> None:
    response = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"route":"knowledge"}'}}],
            "usage": usage,
        },
    )
    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(lambda request: response),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(http, api_key="secret")
        with pytest.raises(StructuredLLMProtocolError, match="token usage"):
            await adapter.generate(_request(), RouteDecision)


@pytest.mark.asyncio
async def test_http_400_is_not_retried_and_error_is_sanitized() -> None:
    attempts = 0
    api_key = "secret-never-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, text=f"bad request Authorization: Bearer {api_key}")

    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(
            http,
            api_key=api_key,
            retry_policy=StructuredLLMRetryPolicy(max_attempts=3),
        )
        with pytest.raises(StructuredLLMHTTPError) as exc_info:
            await adapter.generate(_request(), RouteDecision)

    assert attempts == 1
    assert api_key not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)
    assert "400" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 500])
async def test_retryable_http_failures_are_bounded(status_code: int) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, text="provider unavailable")

    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(
            http,
            api_key="secret",
            retry_policy=StructuredLLMRetryPolicy(max_attempts=3),
        )
        with pytest.raises(StructuredLLMHTTPError, match=str(status_code)):
            await adapter.generate(_request(), RouteDecision)

    assert attempts == 3


@pytest.mark.asyncio
async def test_transport_failure_is_retried_and_sanitized() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("Authorization: Bearer secret-never-leak", request=request)

    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(
            http,
            api_key="secret-never-leak",
            retry_policy=StructuredLLMRetryPolicy(max_attempts=2),
        )
        with pytest.raises(StructuredLLMTransportError) as exc_info:
            await adapter.generate(_request(), RouteDecision)

    assert attempts == 2
    assert "secret-never-leak" not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_timeout_is_retried_up_to_max_attempts() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(
        base_url="https://llm.example.test/v1/",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(
            http,
            api_key="secret",
            retry_policy=StructuredLLMRetryPolicy(max_attempts=2),
        )
        with pytest.raises(StructuredLLMTransportError, match="transport failure"):
            await adapter.generate(_request(), RouteDecision)

    assert attempts == 2


@pytest.mark.asyncio
async def test_unknown_usage_request_id_raises_lookup_error() -> None:
    async with httpx.AsyncClient(base_url="https://llm.example.test/v1/") as http:
        adapter = OpenAICompatibleStructuredLLMAdapter(http, api_key="secret")
        with pytest.raises(LookupError, match="unknown LLM request_id"):
            await adapter.get_usage("missing")


def test_retry_policy_requires_positive_attempt_count() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        StructuredLLMRetryPolicy(max_attempts=0)
