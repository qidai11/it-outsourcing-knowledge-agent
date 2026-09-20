from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from project_agent.application.ports.llm import (
    LLMTokenUsage,
    StructuredLLMRequest,
)
from project_agent.infrastructure.llm.errors import (
    StructuredLLMHTTPError,
    StructuredLLMProtocolError,
    StructuredLLMSchemaError,
    StructuredLLMTransportError,
)

TStructured = TypeVar("TStructured", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StructuredLLMRetryPolicy:
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


class OpenAICompatibleStructuredLLMAdapter:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        retry_policy: StructuredLLMRetryPolicy | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self._http = http
        self._api_key = api_key
        self._retry_policy = retry_policy or StructuredLLMRetryPolicy()
        self._request_timeout_seconds = request_timeout_seconds
        self._usage: dict[str, LLMTokenUsage] = {}

    async def generate(
        self,
        request: StructuredLLMRequest,
        response_model: type[TStructured],
    ) -> TStructured:
        payload = {
            "model": request.model_alias,
            "temperature": request.temperature,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            },
        }
        response = await self._post_with_retry(payload)
        content, usage = self._parse_response(response)
        try:
            result = response_model.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            raise StructuredLLMSchemaError(
                "provider returned an invalid structured response"
            ) from exc
        self._usage[request.request_id] = usage
        return result

    async def get_usage(self, request_id: str) -> LLMTokenUsage:
        try:
            return self._usage[request_id]
        except KeyError as exc:
            raise LookupError(f"unknown LLM request_id: {request_id}") from exc

    async def _post_with_retry(self, payload: dict[str, Any]) -> httpx.Response:
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                response = await self._http.post(
                    "chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self._request_timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._retry_policy.max_attempts:
                    raise StructuredLLMTransportError(
                        "structured LLM transport failure after bounded retries"
                    ) from exc
                await asyncio.sleep(0)
                continue

            if 200 <= response.status_code < 300:
                return response

            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt >= self._retry_policy.max_attempts:
                raise StructuredLLMHTTPError(
                    f"structured LLM provider returned HTTP {response.status_code}"
                )
            await asyncio.sleep(0)

        raise AssertionError("retry loop exhausted without returning or raising")

    @staticmethod
    def _parse_response(response: httpx.Response) -> tuple[str, LLMTokenUsage]:
        try:
            body = response.json()
        except ValueError as exc:
            raise StructuredLLMProtocolError("invalid provider response JSON") from exc
        if not isinstance(body, dict):
            raise StructuredLLMProtocolError("invalid provider response shape")
        try:
            choices = body["choices"]
            message = choices[0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise StructuredLLMProtocolError("invalid provider response shape") from exc
        if not isinstance(content, str):
            raise StructuredLLMProtocolError("invalid provider response shape")

        usage = body.get("usage")
        if not isinstance(usage, dict):
            raise StructuredLLMProtocolError("invalid provider token usage")
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if (
            not isinstance(prompt_tokens, int)
            or isinstance(prompt_tokens, bool)
            or not isinstance(completion_tokens, int)
            or isinstance(completion_tokens, bool)
            or prompt_tokens < 0
            or completion_tokens < 0
        ):
            raise StructuredLLMProtocolError("invalid provider token usage")
        return content, LLMTokenUsage(prompt_tokens, completion_tokens)
