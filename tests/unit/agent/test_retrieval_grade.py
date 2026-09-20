from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.fakes.llm import FakeStructuredLLM
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.grade_retrieval import grade_retrieval_node
from project_agent.agent.nodes.models import (
    RetrievalGrade,
    RetrievalGradeReason,
    RetrievalPlan,
)
from project_agent.application.ports.knowledge import KnowledgeChunk


def test_retrieval_grade_accepts_only_consistent_adequate_shape() -> None:
    grade = RetrievalGrade(
        adequate=True,
        reason=RetrievalGradeReason.ADEQUATE,
        second_round_justified=False,
        refined_query=None,
    )

    assert grade.adequate is True
    assert grade.refined_query is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "adequate": True,
            "reason": RetrievalGradeReason.INSUFFICIENT_COVERAGE,
            "second_round_justified": False,
            "refined_query": None,
        },
        {
            "adequate": True,
            "reason": RetrievalGradeReason.ADEQUATE,
            "second_round_justified": True,
            "refined_query": "retry query",
        },
        {
            "adequate": False,
            "reason": RetrievalGradeReason.INSUFFICIENT_COVERAGE,
            "second_round_justified": True,
            "refined_query": None,
        },
        {
            "adequate": False,
            "reason": RetrievalGradeReason.EMPTY_EVIDENCE,
            "second_round_justified": False,
            "refined_query": "must be absent",
        },
    ],
)
def test_retrieval_grade_rejects_inconsistent_shapes(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RetrievalGrade.model_validate(payload)


async def _seed_grade_state(
    *,
    store: InMemoryQAGraphStore,
    retrieval_round: int = 1,
    allow_second_round: bool = True,
) -> tuple[dict[str, object], RetrievalPlan]:
    run_id = uuid4()
    project_id = uuid4()
    document_version_id = uuid4()
    store.seed_query(run_id, "How do I roll back service ALPHA?")
    plan = RetrievalPlan(
        original_query="How do I roll back service ALPHA?",
        standalone_query="service ALPHA rollback",
        exact_identifiers=("ALPHA",),
        identifier_resolutions=(),
        constrained_document_version_ids=(document_version_id,),
        constrained_provider_document_ids=("provider-doc-1",),
        allowed_categories=("runbook",),
        allow_second_round=allow_second_round,
    )
    plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=plan.model_dump(mode="json"),
    )
    bundle_id = await store.save_evidence_bundle(
        run_id=run_id,
        project_id=project_id,
        query_text=plan.original_query,
        chunks=[
            KnowledgeChunk(
                project_id="PRJ-ALPHA",
                document_version_id=str(document_version_id),
                knowledge_space_id="dataset-alpha",
                content="Authorized rollback evidence only.",
                score=0.81,
            )
        ],
    )
    state: dict[str, object] = {
        "run_id": str(run_id),
        "project_id": str(project_id),
        "retrieval_plan_id": str(plan_id),
        "evidence_bundle_id": str(bundle_id),
        "retrieval_round": retrieval_round,
    }
    return state, plan


@pytest.mark.asyncio
async def test_grade_node_persists_usage_and_grade_from_postfiltered_bundle() -> None:
    store = InMemoryQAGraphStore()
    state, _ = await _seed_grade_state(store=store)
    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "adequate": True,
            "reason": "ADEQUATE",
            "second_round_justified": False,
            "refined_query": None,
        },
        input_tokens=19,
        output_tokens=4,
    )

    result = await grade_retrieval_node(
        state,  # type: ignore[arg-type]
        llm=llm,
        llm_usage=llm,
        store=store,
        model_alias="fake-grade-model",
    )

    run_id = __import__("uuid").UUID(state["run_id"])
    assert result["route"] == "govern_evidence"
    assert result["retrieval_grade_id"] is not None
    assert store.telemetry[run_id].input_tokens == 19
    assert store.telemetry[run_id].output_tokens == 4
    grade_record = store.artifacts[__import__("uuid").UUID(result["retrieval_grade_id"])]
    assert grade_record["artifact_type"] == "RETRIEVAL_GRADE"
    call = llm.calls[0]
    assert call.request.request_id == f"{run_id}:qa-retrieval-grade:1"
    assert call.response_model_name == "RetrievalGrade"
    assert "Authorized rollback evidence only." in call.request.user_prompt
    assert "How do I roll back service ALPHA?" in call.request.user_prompt
    assert "Never return or request a new project" in call.request.user_prompt
    assert "authority" in call.request.user_prompt.lower()


@pytest.mark.asyncio
async def test_grade_node_refines_query_without_changing_frozen_scope() -> None:
    store = InMemoryQAGraphStore()
    state, first = await _seed_grade_state(store=store)
    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "adequate": False,
            "reason": "INSUFFICIENT_COVERAGE",
            "second_round_justified": True,
            "refined_query": "deployment rollback procedure exact service identifier",
        },
        input_tokens=21,
        output_tokens=7,
    )

    result = await grade_retrieval_node(
        state,  # type: ignore[arg-type]
        llm=llm,
        llm_usage=llm,
        store=store,
        model_alias="fake-grade-model",
    )

    assert result["route"] == "retrieve_again"
    second = RetrievalPlan.model_validate(
        await store.load_artifact(__import__("uuid").UUID(result["retrieval_plan_id"]))
    )
    assert second.original_query == first.original_query
    assert second.standalone_query == "deployment rollback procedure exact service identifier"
    assert second.exact_identifiers == first.exact_identifiers
    assert second.identifier_resolutions == first.identifier_resolutions
    assert second.constrained_document_version_ids == first.constrained_document_version_ids
    assert second.constrained_provider_document_ids == first.constrained_provider_document_ids
    assert second.allowed_categories == first.allowed_categories
    assert second.allow_second_round is first.allow_second_round


@pytest.mark.asyncio
async def test_grade_node_refuses_when_second_round_is_not_available() -> None:
    store = InMemoryQAGraphStore()
    state, _ = await _seed_grade_state(store=store, retrieval_round=2)
    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "adequate": False,
            "reason": "INSUFFICIENT_RELEVANCE",
            "second_round_justified": True,
            "refined_query": "another query",
        }
    )

    result = await grade_retrieval_node(
        state,  # type: ignore[arg-type]
        llm=llm,
        llm_usage=llm,
        store=store,
        model_alias="fake-grade-model",
    )

    assert result["route"] == "refusal"
    assert result["last_error_code"] == "INSUFFICIENT_EVIDENCE"
    assert result.get("retrieval_plan_id") is None
