from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from project_agent.infrastructure.ragflow.errors import (
    RagflowApiError,
    RagflowHttpError,
    RagflowProtocolError,
)
from project_agent.observability.logging import get_logger
from project_agent.observability.metrics import current_metrics
from project_agent.observability.sanitization import safe_error_fields

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
        return float(
            min(
                self.base_delay_seconds * (2.0 ** (retry_number - 1)),
                self.max_delay_seconds,
            )
        )


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
        operation = _ragflow_operation(method, path)
        start_ns = time.perf_counter_ns()
        try:
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
            data = payload.get("data")
        except BaseException as exc:
            duration_seconds = max(0.0, (time.perf_counter_ns() - start_ns) / 1_000_000_000)
            metrics = current_metrics()
            if metrics is not None:
                metrics.observe_ragflow(
                    operation=operation,
                    outcome="error",
                    duration_seconds=duration_seconds,
                )
            get_logger().error(
                "ragflow_request_failed",
                provider="ragflow",
                operation=operation,
                outcome="error",
                duration_ms=duration_seconds * 1000.0,
                **safe_error_fields(exc),
            )
            raise
        duration_seconds = max(0.0, (time.perf_counter_ns() - start_ns) / 1_000_000_000)
        metrics = current_metrics()
        if metrics is not None:
            metrics.observe_ragflow(
                operation=operation,
                outcome="success",
                duration_seconds=duration_seconds,
            )
        get_logger().info(
            "ragflow_request_completed",
            provider="ragflow",
            operation=operation,
            outcome="success",
            duration_ms=duration_seconds * 1000.0,
        )
        return data

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


def _ragflow_operation(method: str, path: str) -> str:
    normalized_method = method.upper()
    clean_path = path.split("?", 1)[0].rstrip("/")
    parts = [part for part in clean_path.split("/") if part]
    if clean_path == "/api/v1/retrieval" and normalized_method == "POST":
        return "retrieve"
    if clean_path == "/api/v1/datasets":
        if normalized_method == "GET":
            return "dataset_list"
        if normalized_method == "POST":
            return "dataset_create"
    if len(parts) >= 5 and parts[:3] == ["api", "v1", "datasets"]:
        tail = parts[4:]
        if tail == ["documents"]:
            if normalized_method == "POST":
                return "document_upload"
            if normalized_method == "GET":
                return "document_list"
            if normalized_method == "DELETE":
                return "document_delete"
        if len(tail) == 2 and tail[0] == "documents" and normalized_method == "PUT":
            return "document_metadata_update"
        if tail == ["chunks"] and normalized_method == "POST":
            return "parse_start"
    return "other"
