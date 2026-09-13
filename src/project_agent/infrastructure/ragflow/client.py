from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from project_agent.infrastructure.ragflow.errors import (
    RagflowApiError,
    RagflowHttpError,
    RagflowProtocolError,
)

SleepCallable = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RagflowRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds cannot be less than base_delay_seconds")

    def delay_for_retry(self, retry_number: int) -> float:
        if retry_number < 1:
            raise ValueError("retry_number must be >= 1")
        return min(self.base_delay_seconds * (2 ** (retry_number - 1)), self.max_delay_seconds)


class RagflowHttpClient:
    """Small async HTTP boundary for RAGFlow's REST API.

    One ``httpx.AsyncClient`` instance is injected and reused for all requests.
    Only transient transport failures, HTTP 429, and HTTP 5xx are retried.
    RAGFlow application errors (HTTP 200 with ``code != 0``) are surfaced
    immediately so callers do not multiply deterministic side effects.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        retry_policy: RagflowRetryPolicy | None = None,
        sleep: SleepCallable = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("RAGFlow API key cannot be empty")
        self._http = http
        self._api_key = api_key
        self._retry_policy = retry_policy or RagflowRetryPolicy()
        self._sleep = sleep

    async def request_data(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        files: Any = None,
    ) -> Any:
        response = await self._request(method, path, params=params, json=json, files=files)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RagflowProtocolError("RAGFlow response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise RagflowProtocolError("RAGFlow JSON envelope must be an object")

        code = payload.get("code")
        if code != 0:
            raise RagflowApiError(
                code if code is not None else "missing",
                str(payload.get("message", "unknown error")),
            )
        return payload.get("data")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        json: Any,
        files: Any,
    ) -> httpx.Response:
        last_transport_error: httpx.HTTPError | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    files=files,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_transport_error = exc
                if attempt >= self._retry_policy.max_attempts:
                    raise
                await self._sleep(self._retry_policy.delay_for_retry(attempt))
                continue

            if (
                response.status_code == 429 or response.status_code >= 500
            ) and attempt < self._retry_policy.max_attempts:
                await self._sleep(self._retry_policy.delay_for_retry(attempt))
                continue

            if response.status_code >= 400:
                message = self._extract_error_message(response)
                raise RagflowHttpError(response.status_code, message)
            return response

        if last_transport_error is not None:  # defensive; loop always returns/raises
            raise last_transport_error
        raise RuntimeError("unreachable RAGFlow retry state")

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict) and payload.get("message") is not None:
            return str(payload["message"])
        return response.text[:500]
