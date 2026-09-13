from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

TStructured = TypeVar("TStructured", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StructuredLLMRequest:
    request_id: str
    model_alias: str
    system_prompt: str
    user_prompt: str
    temperature: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMTokenUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token usage cannot be negative")


@runtime_checkable
class StructuredLLMPort(Protocol):
    async def generate(
        self,
        request: StructuredLLMRequest,
        response_model: type[TStructured],
    ) -> TStructured: ...


@runtime_checkable
class StructuredLLMUsagePort(Protocol):
    async def get_usage(self, request_id: str) -> LLMTokenUsage: ...
