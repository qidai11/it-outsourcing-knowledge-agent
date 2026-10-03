"""Task 4 RED: case selection, no silent skips and protocol isolation."""
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from project_agent.evaluation.artifacts import ArtifactStore
from project_agent.evaluation.collector import SideEffectSnapshot
from project_agent.evaluation.dataset import load_evaluation_dataset
from project_agent.evaluation.models import TrialClassification
from project_agent.evaluation.runner import EvaluationRunner, select_cases

ROOT = Path(__file__).resolve().parents[3] / 'evaluation' / 'datasets' / 'v0'
DATASET = load_evaluation_dataset(ROOT)
PROJECTS = {'PRJ-RETAIL-ALPHA': str(uuid4()), 'PRJ-LOGISTICS-BETA': str(uuid4())}
STATE = {'evaluation_namespace': 'unit-task4', 'project_ids': PROJECTS,
         'user_ids': {case.user_alias: str(uuid4()) for case in DATASET.cases}}

class Client:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail
    async def create_run(self, **kwargs):
        self.calls.append(('create', kwargs))
        if self.fail:
            raise TimeoutError('api failure')
        return type('Result', (), {'http_status': 201, 'run_id': uuid4(), 'thread_id': uuid4(),
                                   'status': 'QUEUED'})()
    async def poll_run(self, **kwargs):
        self.calls.append(('poll', kwargs))
        return type('Result', (), {'http_status': 200, 'run_id': kwargs['run_id'],
                                   'thread_id': uuid4(), 'status': 'SUCCEEDED'})()
    async def resume_run(self, **kwargs):
        self.calls.append(('resume', kwargs))
        return type('Result', (), {'http_status': 202, 'run_id': kwargs['run_id'],
                                   'thread_id': uuid4(), 'status': 'QUEUED'})()

class Backend:
    def __init__(self):
        self.captures = []
        self.collects = []
        self.run_count = 0
        self.effects = {}
    async def capture_side_effects(self, *, project_id, request_id):
        self.captures.append(request_id)
        return SideEffectSnapshot(
            count=self.effects.get(request_id, 0),
            project_id=project_id, request_id=request_id,
        )
    async def collect(self, *, case, observation, fixture_state, before_state, after_state):
        self.collects.append(observation)
        from project_agent.evaluation.runner import fallback_trial
        return fallback_trial(case, observation.trial_no, observation.classification,
                              business_mode=observation.business_mode,
                              http_status=observation.http_status, run_id=observation.run_id)
    async def count_runs(self, *, project_id, user_id):
        return self.run_count
    async def waiting_hash(self, *, run_id, project_id):
        return 'b' * 64


def test_select_cases_default_and_filters() -> None:
    assert len(select_cases(DATASET)) == 50
    assert [x.case_id for x in select_cases(DATASET, case_ids=['Q044'])] == ['Q044']
    assert all(x.split == 'dev' for x in select_cases(DATASET, split='dev'))
    assert all(x.priority == 'P0' for x in select_cases(DATASET, priority='P0'))
    assert all(DATASET.gold_for(x.case_id).execution.business_mode == 'qa' for x in
               select_cases(DATASET, business_mode='qa'))
    with pytest.raises(ValueError):
        select_cases(DATASET, case_ids=['Q999'])


@pytest.mark.asyncio
async def test_each_selected_case_emits_exactly_one_trial_artifact(tmp_path) -> None:
    store = ArtifactStore(tmp_path, 'run-001')
    backend, client = Backend(), Client()
    runner = EvaluationRunner(DATASET, STATE, store, client, backend)
    results = await runner.run(case_ids=['Q001', 'Q002', 'Q014'])
    assert len(results) == 3
    assert len(list(store.root.glob('cases/*/trial-001.json'))) == 3
    assert __import__('json').loads(store.run_manifest_path.read_text())['selected_case_ids'] == [
        'Q001', 'Q002', 'Q014']
    assert [x.classification for x in results] == [TrialClassification.SCORED,
        TrialClassification.SCORED, TrialClassification.UNSCORABLE_RUNTIME_SCOPE]


@pytest.mark.asyncio
async def test_runtime_scope_unscorable_emits_artifact_without_api_call(tmp_path) -> None:
    client = Client()
    runner = EvaluationRunner(DATASET, STATE, ArtifactStore(tmp_path, 'r'), client, Backend())
    result = await runner.run(case_ids=['Q014', 'Q046', 'Q049'])
    assert not client.calls
    assert all(x.classification is TrialClassification.UNSCORABLE_RUNTIME_SCOPE for x in result)
    assert all(x.error_category == 'FROZEN_RUNTIME_SCOPE' for x in result)


@pytest.mark.asyncio
async def test_runtime_scope_unscorable_set_remains_q014_q046_q049(tmp_path) -> None:
    codes = {x.case_id for x in DATASET.cases if DATASET.gold_for(x.case_id).scoring.status.value ==
             'UNSCORABLE_RUNTIME_SCOPE'}
    assert codes == {'Q014', 'Q046', 'Q049'}


@pytest.mark.asyncio
async def test_timeout_becomes_runner_or_infra_failure_not_skip(tmp_path) -> None:
    runner = EvaluationRunner(DATASET, STATE, ArtifactStore(tmp_path, 'r'), Client(fail=True),
                              Backend())
    results = await runner.run(case_ids=['Q001'])
    assert results[0].classification is TrialClassification.INFRA_FAILURE


@pytest.mark.asyncio
async def test_unexpected_exception_still_emits_failure_artifact(tmp_path) -> None:
    class Explodes(Backend):
        async def collect(self, **kwargs):
            raise ValueError('something unsafe')
    store = ArtifactStore(tmp_path, 'r')
    runner = EvaluationRunner(DATASET, STATE, store, Client(), Explodes())
    result = await runner.run(case_ids=['Q001'])
    assert result[0].classification is TrialClassification.RUNNER_FAILURE
    assert store.trial_path('Q001', 1).exists()
    assert 'something unsafe' not in store.trial_path('Q001', 1).read_text()


@pytest.mark.asyncio
async def test_single_run_protocol_uses_frozen_question_verbatim(tmp_path) -> None:
    client = Client()
    await EvaluationRunner(DATASET, STATE, ArtifactStore(tmp_path, 'r'), client, Backend()).run(
        case_ids=['Q001'])
    assert client.calls[0][1]['query'] == DATASET.cases[0].question


@pytest.mark.asyncio
async def test_authorization_denial_protocol_requires_no_run_creation(tmp_path) -> None:
    class Denied(Client):
        async def create_run(self, **kwargs):
            self.calls.append(('create', kwargs))
            return type('Result', (), {'http_status': 403, 'run_id': None,
                                       'thread_id': None, 'status': None})()
    client, backend = Denied(), Backend()
    result = await EvaluationRunner(DATASET, STATE, ArtifactStore(tmp_path, 'r'),
                                    client, backend).run(case_ids=['Q040'])
    assert result[0].classification is TrialClassification.SCORED
    assert not backend.collects or backend.collects[0].run_id is None
    assert backend.collects[0].request_id == "eval-v0-q040-trial-001"
    assert client.calls[0][1]['overrides']['role'] == 'project_manager'


@pytest.mark.asyncio
async def test_setup_then_run_is_case_order_independent(tmp_path) -> None:
    client = Client()
    result = await EvaluationRunner(DATASET, STATE, ArtifactStore(tmp_path, 'r'),
                                    client, Backend()).run(case_ids=['Q038'])
    calls = [c for c in client.calls if c[0] == 'create']
    assert len(calls) == 2
    assert calls[1][1]['query'] == next(c.question for c in DATASET.cases if c.case_id == 'Q038')
    assert calls[1][1]['thread_id'] is not None
    assert result[0].classification is TrialClassification.SCORED


@pytest.mark.asyncio
async def test_issue_create_rebinds_both_side_effect_snapshots_to_persisted_request_id(
    tmp_path,
) -> None:
    class PersistedRequestBackend(Backend):
        async def request_id_for_run(self, *, run_id, project_id):
            return "persisted-q016-request"

    backend = PersistedRequestBackend()
    client = Client()

    result = await EvaluationRunner(
        DATASET,
        STATE,
        ArtifactStore(tmp_path, "persisted-request-id"),
        client,
        backend,
    ).run(case_ids=["Q016"])

    assert result[0].classification is TrialClassification.SCORED
    assert backend.captures == [
        "persisted-q016-request",
        "persisted-q016-request",
    ]
    assert backend.collects[0].request_id == "persisted-q016-request"


@pytest.mark.asyncio
async def test_setup_then_run_still_measures_q037_after_failed_prior_context(
    tmp_path,
) -> None:
    class FailedPriorContext(Client):
        def __init__(self) -> None:
            super().__init__()
            self.poll_count = 0

        async def poll_run(self, **kwargs):
            self.calls.append(("poll", kwargs))
            self.poll_count += 1
            status = "FAILED" if self.poll_count == 1 else "REFUSED"
            return type(
                "Result",
                (),
                {
                    "http_status": 200,
                    "run_id": kwargs["run_id"],
                    "thread_id": uuid4(),
                    "status": status,
                },
            )()

    client = FailedPriorContext()
    backend = Backend()

    result = await EvaluationRunner(
        DATASET,
        STATE,
        ArtifactStore(tmp_path, "q037-failed-setup"),
        client,
        backend,
    ).run(case_ids=["Q037"])

    creates = [
        call
        for call in client.calls
        if call[0] == "create"
    ]

    assert len(creates) == 2
    assert creates[0][1]["business_mode"] == "qa"
    assert creates[1][1]["business_mode"] == "issue_create"
    assert creates[1][1]["query"] == next(
        case.question
        for case in DATASET.cases
        if case.case_id == "Q037"
    )
    assert creates[1][1]["thread_id"] is not None
    assert (
        result[0].classification
        is TrialClassification.SCORED
    )


@pytest.mark.asyncio
async def test_waiting_confirmation_resume_uses_persisted_payload_hash(tmp_path) -> None:
    class Waiting(Client):
        async def poll_run(self, **kwargs):
            self.calls.append(('poll', kwargs))
            value = 'WAITING_CONFIRMATION' if kwargs.get('until_waiting') else 'SUCCEEDED'
            return type('Result', (), {'http_status': 200, 'run_id': kwargs['run_id'],
                                       'thread_id': uuid4(), 'status': value})()
    backend, client = Backend(), Waiting()
    result = await EvaluationRunner(DATASET, STATE, ArtifactStore(tmp_path, 'r'),
                                    client, backend).run(case_ids=['Q018'])
    resume = next(x for x in client.calls if x[0] == 'resume')[1]
    assert resume['request_payload_hash'] == 'b'*64
    assert result[0].classification is TrialClassification.SCORED


@pytest.mark.asyncio
async def test_same_request_replay_and_response_loss_use_scenario_driver(tmp_path) -> None:
    class Scenario:
        def request_id(self, case):
            return 'fixed-' + case.case_id
        async def execute(self, case, run_id):
            from project_agent.evaluation.scenarios import ScenarioOutcome
            backend.effects[self.request_id(case)] = 1
            return ScenarioOutcome(request_id=self.request_id(case), status='RECONCILED')
    backend = Backend()
    runner = EvaluationRunner(DATASET, STATE, ArtifactStore(tmp_path, 'r'), Client(),
                              backend, scenario_driver=Scenario())
    results = await runner.run(case_ids=['Q044','Q045'])
    assert len(results) == 2
    assert all(x.classification == TrialClassification.SCORED for x in results)
    assert backend.captures == ['fixed-Q044', 'fixed-Q044', 'fixed-Q045', 'fixed-Q045']


@pytest.mark.asyncio
async def test_default_run_emits_fifty_artifacts_even_when_api_is_unavailable(tmp_path) -> None:
    store = ArtifactStore(tmp_path, 'full-default')
    results = await EvaluationRunner(DATASET, STATE, store, Client(fail=True), Backend()).run()
    assert len(results) == 50
    assert len(list(store.root.glob('cases/*/trial-001.json'))) == 50
    assert {item.case_id for item in results if item.classification is
            TrialClassification.UNSCORABLE_RUNTIME_SCOPE} == {'Q014', 'Q046', 'Q049'}
    assert any(item.classification is TrialClassification.INFRA_FAILURE for item in results)


@pytest.mark.asyncio
async def test_failure_after_run_creation_preserves_observed_run_trace(tmp_path) -> None:
    class FailsAfterRun(Backend):
        async def capture_side_effects(self, *, project_id, request_id):
            if self.captures:
                raise ValueError('synthetic failure after run creation')
            return await super().capture_side_effects(project_id=project_id,
                                                      request_id=request_id)
    client = Client()
    result = await EvaluationRunner(DATASET, STATE, ArtifactStore(tmp_path, 'trace'),
                                    client, FailsAfterRun()).run(case_ids=['Q001'])
    created = client.calls[0][1]
    assert created['query'] == DATASET.cases[0].question
    assert result[0].classification is TrialClassification.RUNNER_FAILURE
    assert result[0].run_id is not None
    assert result[0].http_status == 201


@pytest.mark.asyncio
async def test_secret_bearing_collector_result_becomes_safe_failure_and_next_case_runs(
    tmp_path,
) -> None:
    """A bad Collector field must not interrupt the 1-artifact-per-case contract."""
    from project_agent.evaluation.runner import fallback_trial

    class UnsafeCollector(Backend):
        async def collect(self, *, case, observation, fixture_state, before_state, after_state):
            trial = fallback_trial(
                case, observation.trial_no, TrialClassification.SCORED,
                business_mode=observation.business_mode, run_id=observation.run_id,
            )
            if case.case_id == "Q001":
                return replace(trial, metadata={"authorization": "Bearer sensitive-value"})
            return trial

    store = ArtifactStore(tmp_path, "unsafe-collector")
    results = await EvaluationRunner(
        DATASET, STATE, store, Client(), UnsafeCollector(),
    ).run(case_ids=["Q001", "Q002"])
    assert [result.classification for result in results] == [
        TrialClassification.RUNNER_FAILURE, TrialClassification.SCORED,
    ]
    assert len(list(store.root.glob("cases/*/trial-001.json"))) == 2
    assert "sensitive-value" not in store.trial_path("Q001", 1).read_text()


@pytest.mark.asyncio
async def test_setup_run_is_not_misattributed_when_measured_post_times_out(tmp_path) -> None:
    """A successful setup Run is never misrepresented as the failed measured Run."""
    class MeasuredCreateTimesOut(Client):
        async def create_run(self, **kwargs):
            if len([entry for entry in self.calls if entry[0] == "create"]) == 1:
                self.calls.append(("create", kwargs))
                raise TimeoutError("measured POST timed out")
            return await super().create_run(**kwargs)

    client = MeasuredCreateTimesOut()
    result = await EvaluationRunner(
        DATASET, STATE, ArtifactStore(tmp_path, "setup-timeout"), client, Backend(),
    ).run(case_ids=["Q038"])
    assert len([entry for entry in client.calls if entry[0] == "create"]) == 2
    assert result[0].classification is TrialClassification.INFRA_FAILURE
    assert result[0].run_id is None
    assert "setup_run_id" in result[0].metadata
