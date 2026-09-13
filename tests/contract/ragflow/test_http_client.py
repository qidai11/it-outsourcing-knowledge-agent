from __future__ import annotations

import httpx
import pytest

from project_agent.infrastructure.ragflow.client import RagflowHttpClient, RagflowRetryPolicy
from project_agent.infrastructure.ragflow.errors import RagflowHttpError


@pytest.mark.asyncio
async def test_retries_429_and_5xx_then_returns_success() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"code": 429, "message": "rate limited"})
        if attempts == 2:
            return httpx.Response(503, json={"code": 503, "message": "busy"})
        return httpx.Response(200, json={"code": 0, "data": {"ok": True}})

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = RagflowHttpClient(
            http,
            api_key="secret",
            retry_policy=RagflowRetryPolicy(
                max_attempts=3,
                base_delay_seconds=0.01,
                max_delay_seconds=0.02,
            ),
            sleep=fake_sleep,
        )
        data = await client.request_data("GET", "/api/v1/datasets")

    assert data == {"ok": True}
    assert attempts == 3
    assert sleeps == [0.01, 0.02]


@pytest.mark.asyncio
async def test_retries_timeout_but_stops_at_bound() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    async def no_sleep(_: float) -> None:
        return None

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = RagflowHttpClient(
            http,
            api_key="secret",
            retry_policy=RagflowRetryPolicy(
                max_attempts=2, base_delay_seconds=0, max_delay_seconds=0
            ),
            sleep=no_sleep,
        )
        with pytest.raises(httpx.ReadTimeout):
            await client.request_data("GET", "/api/v1/datasets")

    assert attempts == 2


@pytest.mark.asyncio
async def test_does_not_retry_non_429_4xx() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, json={"code": 400, "message": "bad input"})

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = RagflowHttpClient(http, api_key="secret")
        with pytest.raises(RagflowHttpError) as exc_info:
            await client.request_data("GET", "/api/v1/datasets")

    assert exc_info.value.status_code == 400
    assert attempts == 1
