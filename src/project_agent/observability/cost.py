from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CostEstimate:
    microunits: int
    currency: str
    configured: bool


@dataclass(frozen=True, slots=True)
class TokenCostPolicy:
    input_microunits_per_million_tokens: int | None
    output_microunits_per_million_tokens: int | None
    currency: str = "USD"

    def __post_init__(self) -> None:
        input_rate = self.input_microunits_per_million_tokens
        output_rate = self.output_microunits_per_million_tokens
        if (input_rate is None) != (output_rate is None):
            raise ValueError(
                "input and output token prices must be both configured or both omitted"
            )
        if input_rate is not None and input_rate < 0:
            raise ValueError("input token price must be non-negative")
        if output_rate is not None and output_rate < 0:
            raise ValueError("output token price must be non-negative")

        normalized_currency = self.currency.strip().upper()
        if (
            len(normalized_currency) != 3
            or not normalized_currency.isascii()
            or not normalized_currency.isalpha()
        ):
            raise ValueError("currency must be exactly three ASCII letters")
        object.__setattr__(self, "currency", normalized_currency)

    @classmethod
    def unconfigured(cls, currency: str = "USD") -> TokenCostPolicy:
        return cls(None, None, currency)

    def estimate(self, *, input_tokens: int, output_tokens: int) -> CostEstimate:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")

        input_rate = self.input_microunits_per_million_tokens
        output_rate = self.output_microunits_per_million_tokens
        if input_rate is None or output_rate is None:
            return CostEstimate(microunits=0, currency=self.currency, configured=False)

        numerator = input_tokens * input_rate + output_tokens * output_rate
        return CostEstimate(
            microunits=numerator // 1_000_000,
            currency=self.currency,
            configured=True,
        )


_current_cost_policy: ContextVar[TokenCostPolicy | None] = ContextVar(
    "project_agent_current_cost_policy",
    default=None,
)


@contextmanager
def cost_policy_context(policy: TokenCostPolicy) -> Iterator[None]:
    token = _current_cost_policy.set(policy)
    try:
        yield
    finally:
        _current_cost_policy.reset(token)


def current_cost_policy() -> TokenCostPolicy:
    policy = _current_cost_policy.get()
    if policy is None:
        return TokenCostPolicy.unconfigured()
    return policy
