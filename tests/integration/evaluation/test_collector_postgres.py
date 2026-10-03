"""Live WS8 Collector gate: isolated evaluation database, never the primary DB.

The Task 2 fixture owns cleanup. All Task 3 rows are uncommitted and rolled back
at session close, so neither accepted fixtures nor unrelated runs are modified.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.evaluation.collector import (
    RunObservation,
    SqlAlchemyTrialReader,
    TrialCollector,
)
from project_agent.evaluation.models import TrialClassification
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    AnswerModel,
    CitationModel,
    EvidenceBundleModel,
    EvidenceSnapshotModel,
    IdempotencyRecordModel,
    IssueCandidateModel,
    IssueDraftModel,
    SandboxIssueModel,
    ThreadModel,
    ToolConfirmationModel,
)
from project_agent.infrastructure.db.repositories.qa_graph import SqlAlchemyQAGraphStore

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set RUN_POSTGRES_INTEGRATION=1 and WS8_EVAL_DATABASE_URL for real PostgreSQL",
)


def _case(dataset):  # type: ignore[no-untyped-def]
    return next(item for item in dataset.cases if item.case_id == "Q001")


async def _run(session, case, state):  # type: ignore[no-untyped-def]
    project_id = UUID(str(state["project_ids"][case.project_code]))
    user_id = UUID(str(state["user_ids"][case.user_alias]))
    thread_id, run_id = uuid4(), uuid4()
    session.add(ThreadModel(id=thread_id, company_id=UUID(str(state["company_id"])),
                            project_id=project_id, user_id=user_id,
                            title="WS8 Task3 isolated test"))
    await session.flush()
    now = datetime.now(UTC)
    session.add(AgentRunModel(
        id=run_id, thread_id=thread_id, company_id=UUID(str(state["company_id"])),
        project_id=project_id, user_id=user_id, business_mode="qa",
        status="SUCCEEDED", started_at=now - timedelta(seconds=2), finished_at=now,
        input_tokens=10, output_tokens=3, total_tokens=13, retrieval_rounds=2,
        model_alias="fake", prompt_version="1", prompt_content_hash="testhash",
    ))
    await session.flush()
    return run_id, project_id


@pytest.mark.asyncio
async def test_collector_postgres_retrieval_round_and_governed_citation(
    prepared_postgres,
):  # type: ignore[no-untyped-def]
    dataset, _namespace, sessions, state = prepared_postgres
    case = _case(dataset)
    async with sessions() as session:
        run_id, project_id = await _run(session, case, state)
        versions = state["document_version_ids"]
        store = SqlAlchemyQAGraphStore(session)
        first = await store.save_evidence_bundle(
            run_id=run_id, project_id=project_id, query_text=case.question,
            retrieval_round=1, chunks=[KnowledgeChunk(
                project_id=case.project_code, document_version_id=str(versions["A-REQ-001"]),
                content="authorized initial candidate", score=0.7,
            )],
        )
        second = await store.save_evidence_bundle(
            run_id=run_id, project_id=project_id, query_text=case.question,
            retrieval_round=2, chunks=[KnowledgeChunk(
                project_id=case.project_code, document_version_id=str(versions["A-API-001"]),
                content="authorized second candidate", score=0.8,
            )],
        )
        empty = await store.save_evidence_bundle(
            run_id=run_id, project_id=project_id, query_text=case.question,
            retrieval_round=3, chunks=[],
        )
        assert await store.load_evidence_bundle(empty) == ()
        rows = (await session.scalars(select(EvidenceSnapshotModel).where(
            EvidenceSnapshotModel.bundle_id.in_([first, second, empty])
        ))).all()
        assert sorted(row.metadata_json["retrieval_round"] for row in rows) == [1, 2, 3]
        assert len([row for row in rows if row.source_type == "retrieval_round_marker"]) == 1
        governed = EvidenceBundleModel(run_id=run_id, query_text=case.question)
        session.add(governed)
        await session.flush()
        evidence = EvidenceSnapshotModel(
            bundle_id=governed.id, project_id=project_id,
            document_version_id=UUID(str(versions["A-REQ-001"])),
            source_type="governed_evidence", source_ref="governed:E1",
            content="accepted source", rank=1,
            metadata_json={"lifecycle_status": "PUBLISHED", "is_current": True},
        )
        session.add(evidence)
        await session.flush()
        answer = AnswerModel(run_id=run_id, answer_text="Answer [E1]")
        session.add(answer)
        await session.flush()
        session.add(CitationModel(answer_id=answer.id, evidence_snapshot_id=evidence.id,
                                  citation_no=1))
        session.add(AgentEventModel(run_id=run_id, sequence_no=1,
                                    event_type="RUN_QUEUED",
                                    payload_json={"query_text": case.question}))
        session.add(AgentEventModel(run_id=run_id, sequence_no=2,
                                    event_type="RUN_SUCCEEDED", payload_json={}))
        await session.flush()
        reader = SqlAlchemyTrialReader(session)
        trial = await TrialCollector(reader).collect(
            case=case, run_observation=RunObservation(
                trial_no=1, run_id=run_id, http_status=200,
                request_id="ws8-task3-no-issue",
                classification=TrialClassification.SCORED),
            fixture_state=state,
            before_state=await reader.capture_side_effects(project_id=project_id,
                                                              request_id="ws8-task3-no-issue"),
            after_state=await reader.capture_side_effects(project_id=project_id,
                                                             request_id="ws8-task3-no-issue"),
        )
        assert [item.round_no for item in trial.retrieval_rounds] == [1, 2, 3]
        assert trial.final_retrieval_round == 3
        assert trial.retrieval_rounds[2].candidates == ()
        assert [r.candidates[0].doc_code for r in trial.retrieval_rounds[:2]] == [
            "A-REQ-001", "A-API-001",
        ]
        assert trial.governed_evidence[0].doc_code == "A-REQ-001"
        assert trial.citations[0].doc_code == "A-REQ-001"
        assert trial.answer == "Answer [E1]"
        assert trial.total_tokens == 13
        with pytest.raises(ValueError, match="project"):
            await reader.read(run_id=run_id, project_id=uuid4(), request_id=None)
        # No commit: live fixture cleanup cannot be blocked by our test rows.


@pytest.mark.asyncio
async def test_collector_postgres_issue_is_scoped_to_evaluation_request(
    prepared_postgres,
):  # type: ignore[no-untyped-def]
    from project_agent.evaluation.fixtures import fixture_uuid

    dataset, namespace, sessions, state = prepared_postgres
    case = _case(dataset)
    async with sessions() as session:
        run_id, project_id = await _run(session, case, state)
        request_id = f"ws8-task3-{uuid4().hex}"
        reader = SqlAlchemyTrialReader(session)
        before = await reader.capture_side_effects(project_id=project_id,
                                                    request_id=request_id)
        assert before.count == 0  # Task 2's seven seeded issues do not count.
        draft = IssueDraftModel(
            run_id=run_id, project_id=project_id,
            created_by=UUID(str(state["user_ids"][case.user_alias])),
            title="isolated draft", description="synthetic fixture", issue_type="BUG",
            proposed_priority="HIGH", status="CREATED",
        )
        session.add(draft)
        await session.flush()
        sandbox_project_id = fixture_uuid(
            dataset.dataset_version, f"sandbox-project:{case.project_code}",
            evaluation_namespace=namespace,
        )
        created = SandboxIssueModel(
            project_id=project_id, sandbox_project_id=sandbox_project_id,
            issue_key=f"WS8-T3-{uuid4().hex[:8]}", title="new eval-only issue",
            description="synthetic", issue_type="BUG", priority="HIGH",
            status="OPEN", reporter_id=UUID(str(state["user_ids"][case.user_alias])),
            client_request_id=request_id,
        )
        session.add(created)
        await session.flush()
        seeded = (await session.scalars(select(SandboxIssueModel).where(
            SandboxIssueModel.project_id == project_id,
            SandboxIssueModel.client_request_id.is_(None),
        ))).first()
        assert seeded is not None
        session.add(IssueCandidateModel(issue_draft_id=draft.id,
                                        sandbox_issue_id=seeded.id, rank=1))
        session.add(ToolConfirmationModel(run_id=run_id, tool_name="create_sandbox_issue",
                                          request_payload_hash="hash", status="CONFIRMED"))
        session.add(IdempotencyRecordModel(
            namespace="sandbox_issue_create", request_id=request_id, project_id=project_id,
            status="COMPLETED", resource_type="sandbox_issue", resource_id=created.issue_key,
            response_json={"issue_key": created.issue_key, "status": "OPEN"},
        ))
        await session.flush()
        after = await reader.capture_side_effects(project_id=project_id,
                                                   request_id=request_id)
        assert after.count == 1
        trial = await TrialCollector(reader).collect(
            case=case, run_observation=RunObservation(
                trial_no=1, run_id=run_id, request_id=request_id,
                reconciliation_outcome="RECONCILED"),
            fixture_state=state, before_state=before, after_state=after,
        )
        assert trial.issue is not None
        assert trial.issue.side_effect_count_before == 0
        assert trial.issue.side_effect_count_after == 1
        assert trial.issue.issue_key == created.issue_key
        assert trial.issue.metadata["candidate_issue_keys"] == [seeded.issue_key]
        assert trial.issue.confirmation_state == "CONFIRMED"
        assert trial.issue.metadata["idempotency_status"] == "COMPLETED"
        assert trial.issue.reconciliation_outcome == "RECONCILED"
        assert (await reader.capture_side_effects(project_id=uuid4(),
                                                 request_id=request_id)).count == 0
