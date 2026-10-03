"""TDD contract for the WS8 read-only raw trial collector."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace as Row
from uuid import uuid4

import pytest

from project_agent.evaluation.collector import (
    RunFacts,
    RunObservation,
    SideEffectSnapshot,
    TrialCollector,
)
from project_agent.evaluation.models import EvaluationCase, TrialClassification

PROJECT_ID, VERSION_ID, RUN_ID, THREAD_ID = (uuid4() for _ in range(4))
TIME = datetime(2026, 9, 26, tzinfo=UTC)
CASE = EvaluationCase(
    case_id="Q001", split="acceptance", priority="P0", project_code="PRJ-RETAIL-ALPHA",
    user_alias="alpha_dev", user_role="developer", question_type="knowledge_qa",
    question="Where is REQ-1?", expected_behavior="answer", expected_source_type="requirement",
    expected_identifier="REQ-1", expected_project_scope="PRJ-RETAIL-ALPHA", notes=None,
)
FIXTURE = {
    "project_ids": {CASE.project_code: PROJECT_ID},
    "document_version_ids": {"A-REQ-001": VERSION_ID},
    "user_ids": {CASE.user_alias: uuid4()},
}


class FakeReader:
    def __init__(self, facts: RunFacts) -> None:
        self.facts = facts
        self.calls: list[tuple[object, object, object]] = []

    async def read(self, *, run_id, project_id, request_id):  # type: ignore[no-untyped-def]
        self.calls.append((run_id, project_id, request_id))
        return self.facts


async def collect(
    facts: RunFacts, *, observation: RunObservation | None = None
):  # type: ignore[no-untyped-def]
    reader = FakeReader(facts)
    trial = await TrialCollector(reader).collect(
        case=CASE,
        run_observation=observation or RunObservation(trial_no=1, run_id=RUN_ID, http_status=200),
        fixture_state=FIXTURE,
        before_state=SideEffectSnapshot(count=0),
        after_state=SideEffectSnapshot(count=0),
    )
    return trial, reader


def run(**kwargs):  # type: ignore[no-untyped-def]
    data = dict(
        id=RUN_ID, thread_id=THREAD_ID, project_id=PROJECT_ID,
        user_id=FIXTURE["user_ids"][CASE.user_alias], status="SUCCEEDED",
        business_mode="qa", started_at=TIME,
        finished_at=TIME + timedelta(seconds=2),
                model_alias="llm", prompt_version="v1", prompt_content_hash="sha", input_tokens=23,
                output_tokens=9, total_tokens=32, retrieval_rounds=2)
    data.update(kwargs)
    return Row(**data)


def snap(*, round_no=1, source_type="retrieval_candidate", rank=1, version=VERSION_ID,
         marker=False, metadata=None):  # type: ignore[no-untyped-def]
    extra = {"retrieval_round": round_no}
    if marker:
        extra["retrieval_round_marker"] = True
    extra.update(metadata or {})
    return Row(id=uuid4(), bundle_id=uuid4(), project_id=PROJECT_ID,
               document_version_id=None if marker else version,
               source_type="retrieval_round_marker" if marker else source_type,
               source_ref="evaluation:empty-round" if marker else "chunk", rank=rank, score=None,
               metadata_json=extra)


@pytest.mark.asyncio
async def test_collector_reads_run_lifecycle_and_telemetry() -> None:
    facts = RunFacts(run=run(), events=(
        Row(sequence_no=1, event_type="RUN_QUEUED", payload_json={"query_text": CASE.question}),
        Row(sequence_no=2, event_type="RUN_STARTED", payload_json={}),
        Row(sequence_no=3, event_type="RUN_COMPLETED", payload_json={}),
    ))
    trial, reader = await collect(facts)
    assert trial.classification == TrialClassification.SCORED
    assert trial.status_transitions == ("QUEUED", "RUNNING", "SUCCEEDED")
    assert trial.event_types == ("RUN_QUEUED", "RUN_STARTED", "RUN_COMPLETED")
    assert trial.latency_ms == 2000
    assert (trial.input_tokens, trial.output_tokens, trial.total_tokens) == (23, 9, 32)
    assert trial.query_sha256 == sha256(CASE.question.encode()).hexdigest()
    assert reader.calls == [(RUN_ID, PROJECT_ID, None)]


@pytest.mark.asyncio
async def test_collector_maps_document_version_uuid_to_frozen_doc_code() -> None:
    trial, _ = await collect(RunFacts(run=run(), snapshots=(snap(),)))
    assert trial.retrieval_rounds[0].candidates[0].doc_code == "A-REQ-001"
    unknown, _ = await collect(RunFacts(run=run(), snapshots=(snap(version=uuid4()),)))
    assert unknown.retrieval_rounds[0].candidates[0].doc_code is None


@pytest.mark.asyncio
async def test_collector_reads_governed_evidence_and_citations() -> None:
    governed = snap(
        source_type="governed_evidence",
        metadata={"lifecycle_status": "PUBLISHED", "is_current": True},
    )
    answer = Row(id=uuid4(), answer_text="REQ-1 is active", refusal_reason=None)
    citation = Row(id=uuid4(), answer_id=answer.id, evidence_snapshot_id=governed.id, citation_no=1)
    trial, _ = await collect(RunFacts(
        run=run(), snapshots=(governed,), answer=answer, citations=(citation,),
    ))
    assert len(trial.governed_evidence) == 1
    assert trial.governed_evidence[0].lifecycle_status == "PUBLISHED"
    assert trial.governed_evidence[0].is_current is True
    assert trial.citations[0].evidence_id == str(governed.id)
    assert trial.citations[0].doc_code == "A-REQ-001"


@pytest.mark.asyncio
async def test_collector_reads_answer_and_refusal_reason() -> None:
    trial, _ = await collect(RunFacts(
        run=run(),
        answer=Row(answer_text="No evidence", refusal_reason="NO_AUTHORIZED_EVIDENCE"),
    ))
    assert (trial.answer, trial.refusal_reason) == ("No evidence", "NO_AUTHORIZED_EVIDENCE")


@pytest.mark.asyncio
async def test_collector_reads_answer_draft_and_citation_guard_artifacts() -> None:
    events = (
        Row(sequence_no=1, event_type="ARTIFACT_AVAILABLE", payload_json={
            "artifact_type": "ANSWER_DRAFT", "artifact": {"answer_text": "draft"},
        }),
        Row(sequence_no=2, event_type="ARTIFACT_AVAILABLE", payload_json={
            "artifact_type": "CITATION_GUARD", "artifact": {"coverage_ok": False},
        }),
    )
    trial, _ = await collect(RunFacts(run=run(), events=events))
    assert trial.metadata["answer_draft_present"] is True
    assert trial.metadata["citation_guard"]["coverage_ok"] is False
    assert "'answer_text': 'draft'" not in str(trial.metadata)


@pytest.mark.asyncio
async def test_collector_distinguishes_first_and_final_retrieval_round() -> None:
    trial, _ = await collect(RunFacts(run=run(), snapshots=(snap(round_no=2), snap(round_no=1))))
    assert [item.round_no for item in trial.retrieval_rounds] == [1, 2]
    assert trial.final_retrieval_round == 2
    assert len(trial.retrieval_rounds[0].candidates) == 1


@pytest.mark.asyncio
async def test_collector_preserves_empty_final_round_without_guessing() -> None:
    trial, _ = await collect(RunFacts(
        run=run(), snapshots=(snap(round_no=1), snap(round_no=2, marker=True)),
    ))
    assert trial.final_retrieval_round == 2
    assert trial.retrieval_rounds[1].candidates == ()
    with pytest.raises(ValueError, match="retrieval_round"):
        await collect(RunFacts(run=run(), snapshots=(snap(metadata={"retrieval_round": None}),)))


@pytest.mark.asyncio
async def test_collector_reads_issue_candidates_and_draft() -> None:
    draft = Row(id=uuid4(), status="DRAFT", title="new draft", proposed_priority="HIGH")
    issue = Row(id=uuid4(), issue_key="ALPHA-22", status="OPEN")
    candidate = Row(rank=1, score=0.8, reasons_json=["same identifier"])
    trial, _ = await collect(RunFacts(
        run=run(), draft=draft, issue_candidates=((candidate, issue),),
    ))
    assert trial.issue is not None and trial.issue.draft_present
    assert trial.issue.metadata["candidate_issue_keys"] == ["ALPHA-22"]
    assert trial.issue.metadata["candidate_status_by_issue"] == {"ALPHA-22": "OPEN"}
    assert trial.issue.metadata["label_as_tool_data"] is True


@pytest.mark.asyncio
async def test_collector_reads_confirmation_state() -> None:
    trial, _ = await collect(RunFacts(
        run=run(), confirmations=(Row(
            status="CONFIRMED", tool_name="create_sandbox_issue", created_at=TIME,
        ),),
    ))
    assert trial.issue is not None and trial.issue.confirmation_state == "CONFIRMED"


@pytest.mark.asyncio
async def test_collector_reads_idempotency_record_and_reconciliation_outcome() -> None:
    trial, _ = await collect(
        RunFacts(run=run(), idempotency=Row(
            status="COMPLETED", request_id="eval-Q001", resource_id="ALPHA-23",
            response_json={"status": "OPEN"},
        )),
        observation=RunObservation(
            trial_no=1, run_id=RUN_ID, request_id="eval-Q001",
            reconciliation_outcome="RECONCILED",
        ),
    )
    assert trial.issue is not None
    assert trial.issue.request_id == "eval-Q001"
    assert trial.issue.issue_key == "ALPHA-23"
    assert trial.issue.status == "OPEN"  # durable idempotent response survives lost HTTP reply
    assert trial.issue.reconciliation_outcome == "RECONCILED"
    assert trial.issue.metadata["idempotency_status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_collector_counts_only_evaluation_owned_sandbox_side_effects() -> None:
    trial, reader = await collect(
        RunFacts(run=run(), sandbox_issues=(Row(issue_key="ALPHA-24", status="OPEN"),)),
        observation=RunObservation(trial_no=1, run_id=RUN_ID, request_id="eval-Q001"),
    )
    assert reader.calls[0][2] == "eval-Q001"
    assert trial.issue is not None and trial.issue.issue_key == "ALPHA-24"
    # A seeded issue with no matching client_request_id must never be counted.
    assert trial.issue.side_effect_count_before == 0
    assert trial.issue.side_effect_count_after == 0


@pytest.mark.asyncio
async def test_collector_does_not_invent_run_for_denied_or_unscorable_case() -> None:
    reader = FakeReader(RunFacts())
    trial = await TrialCollector(reader).collect(case=CASE,
        run_observation=RunObservation(
            trial_no=2, http_status=403, classification=TrialClassification.SCORED,
        ),
        fixture_state=FIXTURE,
        before_state=SideEffectSnapshot(count=0),
        after_state=SideEffectSnapshot(count=0),
    )
    assert trial.run_id is None and trial.http_status == 403
    assert trial.status_transitions == ()
    assert not reader.calls


@pytest.mark.asyncio
async def test_collector_rejects_cross_project_run() -> None:
    with pytest.raises(ValueError, match="project"):
        await collect(RunFacts(run=run(project_id=uuid4())))


@pytest.mark.asyncio
async def test_collector_uses_persisted_document_lifecycle_not_fabricated_is_current() -> None:
    document_id = uuid4()
    version = Row(document_id=document_id, version_no=3, lifecycle_status="PUBLISHED")
    document = Row(project_id=PROJECT_ID, document_category="requirement_baseline")
    facts = RunFacts(run=run(), snapshots=(snap(),),
                     documents={VERSION_ID: (version, document, 3)})
    trial, _ = await collect(facts)
    item = trial.retrieval_rounds[0].candidates[0]
    assert item.is_current is True
    assert item.lifecycle_status == "PUBLISHED"
    assert item.project_code == CASE.project_code


@pytest.mark.asyncio
async def test_collector_rejects_cross_project_evidence() -> None:
    invalid = snap(metadata={"project_code": "PRJ-LOGISTICS-BETA"})
    with pytest.raises(ValueError, match="project"):
        await collect(RunFacts(run=run(), snapshots=(invalid,)))
    invalid.project_id = uuid4()
    with pytest.raises(ValueError, match="project"):
        await collect(RunFacts(run=run(), snapshots=(invalid,)))


@pytest.mark.asyncio
async def test_denied_run_preserves_gold_business_mode() -> None:
    trial = await TrialCollector(FakeReader(RunFacts())).collect(
        case=CASE,
        run_observation=RunObservation(
            trial_no=1, http_status=403, business_mode="qa",
        ),
        fixture_state=FIXTURE,
        before_state=SideEffectSnapshot(count=0),
        after_state=SideEffectSnapshot(count=0),
    )
    assert trial.run_id is None
    assert trial.business_mode == "qa"


@pytest.mark.asyncio
async def test_collector_rejects_mismatched_side_effect_capture_scope() -> None:
    reader = FakeReader(RunFacts(run=run()))
    with pytest.raises(ValueError, match="side-effect.*request"):
        await TrialCollector(reader).collect(
            case=CASE,
            run_observation=RunObservation(
                trial_no=1, run_id=RUN_ID, request_id="ws8-intended-request",
            ),
            fixture_state=FIXTURE,
            before_state=SideEffectSnapshot(count=0, request_id="ws8-other-request"),
            after_state=SideEffectSnapshot(count=1, request_id="ws8-intended-request"),
        )
    assert not reader.calls  # fail closed, without inspecting another request's data


@pytest.mark.asyncio
async def test_collector_does_not_fabricate_issue_for_qa_request_id() -> None:
    trial, reader = await collect(
        RunFacts(run=run()),
        observation=RunObservation(
            trial_no=1, run_id=RUN_ID, business_mode="qa", request_id="qa-request-1",
        ),
    )
    assert reader.calls[0][2] == "qa-request-1"
    assert trial.issue is None


@pytest.mark.asyncio
async def test_collector_issue_denial_preserves_request_scope_without_run() -> None:
    reader = FakeReader(RunFacts())
    trial = await TrialCollector(reader).collect(
        case=CASE,
        run_observation=RunObservation(
            trial_no=1, business_mode="issue_create", request_id="issue-request-1",
            http_status=403,
        ),
        fixture_state=FIXTURE,
        before_state=SideEffectSnapshot(count=0),
        after_state=SideEffectSnapshot(count=0),
    )
    assert trial.run_id is None
    assert trial.issue is not None
    assert trial.issue.request_id == "issue-request-1"


@pytest.mark.asyncio
async def test_collector_preserves_ordered_citation_guard_history_for_shadow_ablation() -> None:
    events = (
        Row(sequence_no=1, event_type="ARTIFACT_AVAILABLE", payload_json={
            "artifact_type": "ANSWER_DRAFT", "artifact": {"answer_text": "never persist me"},
        }),
        Row(sequence_no=2, event_type="ARTIFACT_AVAILABLE", payload_json={
            "artifact_type": "CITATION_GUARD", "artifact": {
                "valid": False, "coverage": 0.5, "used_evidence_ids": ["E1"],
            },
        }),
        Row(sequence_no=3, event_type="ARTIFACT_AVAILABLE", payload_json={
            "artifact_type": "CITATION_GUARD", "artifact": {
                "valid": True, "coverage": 1.0, "used_evidence_ids": ["E1", "E2"],
            },
        }),
    )
    trial, _ = await collect(RunFacts(run=run(), events=events))
    assert trial.metadata["citation_guard_history"] == [
        {"valid": False, "coverage": 0.5, "used_evidence_ids": ["E1"]},
        {"valid": True, "coverage": 1.0, "used_evidence_ids": ["E1", "E2"]},
    ]
    assert trial.metadata["citation_guard"] == trial.metadata["citation_guard_history"][-1]
    assert "never persist me" not in str(trial.metadata)


@pytest.mark.asyncio
async def test_collector_accepts_json_serialized_project_id_in_side_effect_scope() -> None:
    # fixture-state.json strings must compare safely with PostgreSQL UUID scope.
    fixture = {
        **FIXTURE,
        "project_ids": {CASE.project_code: str(PROJECT_ID)},
        "user_ids": {CASE.user_alias: str(FIXTURE["user_ids"][CASE.user_alias])},
        "document_version_ids": {"A-REQ-001": str(VERSION_ID)},
    }
    reader = FakeReader(RunFacts(run=run()))
    request_id = "eval-v0-q001-trial-001"
    trial = await TrialCollector(reader).collect(
        case=CASE,
        run_observation=RunObservation(
            trial_no=1,
            run_id=RUN_ID,
            http_status=201,
            request_id=request_id,
        ),
        fixture_state=fixture,
        before_state=SideEffectSnapshot(
            count=0,
            project_id=PROJECT_ID,
            request_id=request_id,
        ),
        after_state=SideEffectSnapshot(
            count=0,
            project_id=PROJECT_ID,
            request_id=request_id,
        ),
    )
    assert trial.classification is TrialClassification.SCORED
    assert reader.calls == [(RUN_ID, PROJECT_ID, request_id)]
