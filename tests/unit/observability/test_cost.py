import pytest

from project_agent.observability.cost import (
    TokenCostPolicy,
    cost_policy_context,
    current_cost_policy,
)


def test_unconfigured_cost_is_zero_and_explicitly_unconfigured() -> None:
    estimate = TokenCostPolicy.unconfigured("USD").estimate(
        input_tokens=1234,
        output_tokens=567,
    )
    assert estimate.microunits == 0
    assert estimate.currency == "USD"
    assert estimate.configured is False


def test_cost_floors_once_after_cumulative_numerator() -> None:
    policy = TokenCostPolicy(333_333, 777_777, "USD")
    estimate = policy.estimate(input_tokens=3, output_tokens=2)
    assert estimate.microunits == (3 * 333_333 + 2 * 777_777) // 1_000_000
    assert estimate.configured is True


def test_price_pair_must_be_both_present_or_both_absent() -> None:
    with pytest.raises(ValueError):
        TokenCostPolicy(100, None, "USD")


def test_negative_tokens_or_prices_are_rejected() -> None:
    with pytest.raises(ValueError):
        TokenCostPolicy(-1, 10, "USD")
    with pytest.raises(ValueError):
        TokenCostPolicy(10, 20, "USD").estimate(input_tokens=-1, output_tokens=0)


def test_cost_policy_context_is_scoped_and_restored() -> None:
    configured = TokenCostPolicy(10, 20, "USD")
    assert current_cost_policy().estimate(input_tokens=1, output_tokens=1).configured is False

    with cost_policy_context(configured):
        assert current_cost_policy() is configured

    assert current_cost_policy().estimate(input_tokens=1, output_tokens=1).configured is False
