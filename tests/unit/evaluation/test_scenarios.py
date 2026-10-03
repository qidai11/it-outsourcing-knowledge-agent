"""Task 4 RED: frozen scenario protocol and production tracker wrapper."""
from pathlib import Path
from uuid import uuid4

import pytest

from project_agent.evaluation.scenarios import (
    ResponseLossProjectTracker,
    fixed_request_uuid,
    load_frozen_scenarios,
)

ROOT = Path(__file__).resolve().parents[3] / 'evaluation' / 'datasets' / 'v0'


def test_frozen_scenario_catalog_is_complete() -> None:
    frozen = load_frozen_scenarios(ROOT)
    assert set(frozen.setups) == {
        'SETUP_ALPHA_DATE_DEFECT_CONTEXT', 'SETUP_ALPHA_DATE_DRAFT_WAITING',
        'SETUP_ALPHA_VIEWER_CONTEXT', 'SETUP_ALPHA_CONFIRMED_CREATE',
    }
    assert set(frozen.faults) == {'FAULT_SAME_REQUEST_REPLAY', 'FAULT_CREATE_RESPONSE_LOSS'}


def test_same_request_replay_uses_one_fixed_request_id() -> None:
    template = 'eval-v0-{case_id}-alpha-confirmed-create'
    assert fixed_request_uuid('namespace-a', 'Q044', template) == fixed_request_uuid(
        'namespace-a', 'Q044', template)
    assert fixed_request_uuid('namespace-a', 'Q044', template) != fixed_request_uuid(
        'namespace-a', 'Q045', template)


@pytest.mark.asyncio
async def test_response_loss_reconcile_uses_request_id_lookup_before_replay() -> None:
    class Tracker:
        def __init__(self):
            self.creates = 0
            self.lookups = 0
        async def create_issue(self, request):
            self.creates += 1
            return 'persisted issue'
        async def get_issue_by_request_id(self, project_id, request_id):
            self.lookups += 1
            return 'persisted issue' if self.creates else None
        async def search_issues(self, request):
            return []
    target = Tracker()
    wrapper = ResponseLossProjectTracker(target)
    with pytest.raises(TimeoutError):
        await wrapper.create_issue(object())
    assert await wrapper.get_issue_by_request_id(str(uuid4()), 'fixed-request') == 'persisted issue'
    assert target.creates == 1 and target.lookups == 1
    assert await wrapper.create_issue(object()) == 'persisted issue'
    assert target.creates == 2  # wrapper does not silently swallow a second invocation


def test_fault_driver_rejects_non_fault_case_before_any_write() -> None:
    from project_agent.evaluation.dataset import load_evaluation_dataset
    from project_agent.evaluation.scenarios import PostgresIssueScenarioDriver

    dataset = load_evaluation_dataset(ROOT)
    driver = object.__new__(PostgresIssueScenarioDriver)
    driver._frozen = load_frozen_scenarios(ROOT)
    driver._namespace = "isolated-unit-test"
    case = next(item for item in dataset.cases if item.case_id == "Q001")
    with pytest.raises(ValueError, match="fault-protocol"):
        driver.request_id(case)
