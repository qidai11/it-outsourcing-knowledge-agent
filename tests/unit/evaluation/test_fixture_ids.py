"""WS8 Task 2 RED: evaluation-only deterministic fixture UUID contracts.

The ID generator is intentionally imported *inside* the tests: when Task 2
implementation is absent, pytest reports clear RED failures rather than a
collection error that would mask the remaining opt-in live test definitions.
"""

from __future__ import annotations

from uuid import UUID


def test_fixture_uuid_is_stable_for_same_dataset_and_logical_key() -> None:
    from project_agent.evaluation.fixtures import fixture_uuid

    first = fixture_uuid("v0", "project:PRJ-RETAIL-ALPHA", evaluation_namespace="ws8-v0-red")
    second = fixture_uuid("v0", "project:PRJ-RETAIL-ALPHA", evaluation_namespace="ws8-v0-red")

    assert isinstance(first, UUID)
    assert first.version == 5
    assert first == second


def test_fixture_uuid_differs_for_different_logical_keys() -> None:
    from project_agent.evaluation.fixtures import fixture_uuid

    alpha = fixture_uuid("v0", "project:PRJ-RETAIL-ALPHA", evaluation_namespace="ws8-v0-red")
    beta = fixture_uuid("v0", "project:PRJ-LOGISTICS-BETA", evaluation_namespace="ws8-v0-red")
    alpha_doc = fixture_uuid("v0", "document:A-API-001", evaluation_namespace="ws8-v0-red")

    assert len({alpha, beta, alpha_doc}) == 3


def test_evaluation_ids_are_namespaced() -> None:
    from project_agent.evaluation.fixtures import fixture_uuid

    key = "project:PRJ-RETAIL-ALPHA"
    one = fixture_uuid("v0", key, evaluation_namespace="ws8-eval-one")
    two = fixture_uuid("v0", key, evaluation_namespace="ws8-eval-two")
    next_version = fixture_uuid("v1", key, evaluation_namespace="ws8-eval-one")

    assert len({one, two, next_version}) == 3
