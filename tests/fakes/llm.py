from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from project_agent.application.ports.llm import LLMTokenUsage, StructuredLLMRequest

TStructured = TypeVar("TStructured", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class FakeLLMCall:
    request: StructuredLLMRequest
    response_model_name: str


@dataclass(frozen=True, slots=True)
class _QueuedResponse:
    raw: Any
    usage: LLMTokenUsage


class FakeStructuredLLM:
    def __init__(self) -> None:
        self._responses: list[_QueuedResponse] = []
        self._usage: dict[str, LLMTokenUsage] = {}
        self.calls: list[FakeLLMCall] = []

    def queue_response(
        self,
        response: Any,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self._responses.append(
            _QueuedResponse(
                raw=response,
                usage=LLMTokenUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ),
            )
        )

    async def generate(
        self,
        request: StructuredLLMRequest,
        response_model: type[TStructured],
    ) -> TStructured:
        if not self._responses:
            raise RuntimeError("no fake structured LLM response queued")
        queued = self._responses.pop(0)
        self.calls.append(
            FakeLLMCall(
                request=request,
                response_model_name=response_model.__name__,
            )
        )
        self._usage[request.request_id] = queued.usage
        return response_model.model_validate(queued.raw)

    async def get_usage(self, request_id: str) -> LLMTokenUsage:
        try:
            return self._usage[request_id]
        except KeyError as exc:
            raise LookupError(f"no usage recorded for request {request_id}") from exc
