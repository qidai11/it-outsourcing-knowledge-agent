from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from tests.fakes.evidence_governance import FakeEvidenceGovernanceRepository
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.llm import FakeStructuredLLM
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.citation_guard import citation_guard_node
from project_agent.agent.nodes.generate_answer import generate_answer_node
from project_agent.agent.nodes.govern_evidence import govern_evidence_node
from project_agent.agent.nodes.grade_retrieval import grade_retrieval_node
from project_agent.agent.nodes.models import RetrievalPlan
from project_agent.agent.nodes.retrieve import retrieve_node
from project_agent.agent.nodes.serialization import serialize_authorized_context
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.application.services.authorization import AuthorizedProjectContext
from project_agent.application.services.citation_guard import CitationGuard
from project_agent.application.services.evidence_governance import (
    DocumentEvidenceMetadata,
    EvidenceGovernanceService,
)
from project_agent.application.services.prompt_config import PromptSnapshot
from project_agent.domain.access import ProjectAccessScope
from project_agent.domain.enums import (
    AuthorityLevel,
    DocumentCategory,
    DocumentLifecycleStatus,
    ProjectRole,
)


@pytest.mark.asyncio
async def test_retrieve_postfilters_governs_and_persists_cited_answer() -> None:
    run_id = uuid4()
    thread_id = uuid4()
    user_id = uuid4()
    company_id = uuid4()
    project_id = uuid4()
    version_id = uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "REQ-3.2.1 是什么？")
    context = AuthorizedProjectContext(
        scope=ProjectAccessScope(
            company_id=company_id,
            user_id=user_id,
            allowed_client_ids=(uuid4(),),
            allowed_project_ids=(project_id,),
            allowed_document_version_ids=(version_id,),
            allowed_document_categories=("requirement_baseline",),
            role_ids=(ProjectRole.DEVELOPER.value,),
            policy_version="test",
        ),
        project_code="PRJ-ALPHA",
        knowledge_space_ids=("dataset-alpha",),
    )
    access_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )
    plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=RetrievalPlan(
            original_query="REQ-3.2.1 是什么？",
            standalone_query="REQ-3.2.1 是什么？",
            exact_identifiers=("REQ-3.2.1",),
            identifier_resolutions=(),
            constrained_document_version_ids=(version_id,),
            allowed_categories=("requirement_baseline",),
        ).model_dump(mode="json"),
    )
    knowledge = FakeKnowledgePort()
    knowledge.add_chunk(
        project_id="PRJ-ALPHA",
        document_version_id=str(version_id),
        knowledge_space_id="dataset-alpha",
        content="Alpha Evidence",
        score=0.7,
    )
    knowledge.add_chunk(
        project_id="PRJ-BETA",
        document_version_id=str(uuid4()),
        knowledge_space_id="dataset-beta",
        content="Beta Evidence",
        score=0.99,
    )
    state = {
        "run_id": str(run_id),
        "thread_id": str(thread_id),
        "user_id": str(user_id),
        "project_id": str(project_id),
        "access_scope_id": str(access_id),
        "retrieval_plan_id": str(plan_id),
        "revision_count": 0,
    }

    retrieved = await retrieve_node(
        state,
        knowledge=knowledge,
        access_policy=ProjectAccessPolicy(),
        store=store,
    )
    state.update(retrieved)
    chunks = await store.load_evidence_bundle(UUID(retrieved["evidence_bundle_id"]))
    assert [chunk.content for chunk in chunks] == ["Alpha Evidence"]
    grade_llm = FakeStructuredLLM()
    grade_llm.queue_response(
        {
            "adequate": True,
            "reason": "ADEQUATE",
            "second_round_justified": False,
            "refined_query": None,
        },
        input_tokens=5,
        output_tokens=1,
    )
    state.update(
        await grade_retrieval_node(
            state,
            llm=grade_llm,
            llm_usage=grade_llm,
            store=store,
            model_alias="fake-grade",
        )
    )
    assert state["route"] == "govern_evidence"

    governance_repo = FakeEvidenceGovernanceRepository()
    governance_repo.records[version_id] = DocumentEvidenceMetadata(
        document_version_id=version_id,
        document_id=uuid4(),
        project_id=project_id,
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        title="Requirements",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        version_no=1,
        version_label="v1",
        effective_from=None,
        effective_to=None,
        is_current=True,
    )
    state.update(
        await govern_evidence_node(
            state,
            evidence_governance=EvidenceGovernanceService(
                governance_repo, today=lambda: date(2026, 8, 8)
            ),
            store=store,
        )
    )

    prompt_id = await store.record_prompt_snapshot(
        run_id=run_id,
        model_alias="fake",
        snapshot=PromptSnapshot(
            config_key="prompt.qa.answer",
            content="Only Evidence.",
            version=1,
            content_hash="h1",
        ),
    )
    state["prompt_snapshot_id"] = str(prompt_id)
    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "claims": [{"text": "Alpha answer", "evidence_ids": ["E1"]}],
            "conflict_disclosure": None,
        },
        input_tokens=30,
        output_tokens=4,
    )
    state.update(
        await generate_answer_node(
            state,
            llm=llm,
            llm_usage=llm,
            store=store,
            model_alias="fake",
        )
    )
    answered = await citation_guard_node(state, guard=CitationGuard(), store=store)

    answer_id = UUID(answered["answer_id"])
    assert store.answers[answer_id]["answer_text"] == "Alpha answer [E1]"
    assert len(store.citations[answer_id]) == 1
    assert store.telemetry[run_id].input_tokens == 35
    assert store.telemetry[run_id].output_tokens == 5
    assert store.telemetry[run_id].retrieval_rounds == 1


@pytest.mark.asyncio
async def test_empty_retrieval_sets_refusal_route_without_llm() -> None:
    run_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "没有证据的问题")
    context = AuthorizedProjectContext(
        scope=ProjectAccessScope(
            company_id=uuid4(),
            user_id=user_id,
            allowed_client_ids=(uuid4(),),
            allowed_project_ids=(project_id,),
            allowed_document_version_ids=(uuid4(),),
            allowed_document_categories=("requirement_baseline",),
            role_ids=("developer",),
            policy_version="test",
        ),
        project_code="PRJ-ALPHA",
        knowledge_space_ids=("dataset-alpha",),
    )
    access_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )
    plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=RetrievalPlan(
            original_query="没有证据的问题",
            standalone_query="没有证据的问题",
            exact_identifiers=(),
            identifier_resolutions=(),
            constrained_document_version_ids=(),
        ).model_dump(mode="json"),
    )
    result = await retrieve_node(
        {
            "run_id": str(run_id),
            "user_id": str(user_id),
            "project_id": str(project_id),
            "access_scope_id": str(access_id),
            "retrieval_plan_id": str(plan_id),
        },
        knowledge=FakeKnowledgePort(),
        access_policy=ProjectAccessPolicy(),
        store=store,
    )
    assert result["route"] == "grade_retrieval"
    assert result["last_error_code"] is None
    assert result["retrieval_round"] == 1
    assert store.telemetry[run_id].retrieval_rounds == 1


@pytest.mark.asyncio
async def test_retrieve_refuses_without_provider_call_when_no_authorized_scope() -> None:
    run_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "scope denied")
    context = AuthorizedProjectContext(
        scope=ProjectAccessScope(
            company_id=uuid4(),
            user_id=user_id,
            allowed_client_ids=(uuid4(),),
            allowed_project_ids=(project_id,),
            allowed_document_version_ids=(),
            allowed_document_categories=("requirement_baseline",),
            role_ids=("developer",),
            policy_version="test",
        ),
        project_code="PRJ-ALPHA",
        knowledge_space_ids=("dataset-alpha",),
    )
    access_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )
    plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=RetrievalPlan(
            original_query="scope denied",
            standalone_query="scope denied",
            exact_identifiers=(),
            identifier_resolutions=(),
            constrained_document_version_ids=(),
            allow_second_round=True,
        ).model_dump(mode="json"),
    )
    knowledge = FakeKnowledgePort()

    result = await retrieve_node(
        {
            "run_id": str(run_id),
            "user_id": str(user_id),
            "project_id": str(project_id),
            "access_scope_id": str(access_id),
            "retrieval_plan_id": str(plan_id),
            "retrieval_round": 0,
        },
        knowledge=knowledge,
        access_policy=ProjectAccessPolicy(),
        store=store,
    )

    assert result["route"] == "refusal"
    assert result["last_error_code"] == "NO_AUTHORIZED_EVIDENCE"
    assert result.get("retrieval_round") is None
    assert knowledge.retrieval_requests == []
    assert store.telemetry[run_id].retrieval_rounds == 0


@pytest.mark.asyncio
async def test_retrieve_hard_stops_before_third_provider_call() -> None:
    run_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    version_id = uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "third retrieval must not happen")
    context = AuthorizedProjectContext(
        scope=ProjectAccessScope(
            company_id=uuid4(),
            user_id=user_id,
            allowed_client_ids=(uuid4(),),
            allowed_project_ids=(project_id,),
            allowed_document_version_ids=(version_id,),
            allowed_document_categories=("requirement_baseline",),
            role_ids=("developer",),
            policy_version="test",
        ),
        project_code="PRJ-ALPHA",
        knowledge_space_ids=("dataset-alpha",),
    )
    access_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )
    plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=RetrievalPlan(
            original_query="third retrieval must not happen",
            standalone_query="third retrieval must not happen",
            exact_identifiers=(),
            identifier_resolutions=(),
            constrained_document_version_ids=(version_id,),
            allow_second_round=True,
        ).model_dump(mode="json"),
    )
    knowledge = FakeKnowledgePort()

    result = await retrieve_node(
        {
            "run_id": str(run_id),
            "user_id": str(user_id),
            "project_id": str(project_id),
            "access_scope_id": str(access_id),
            "retrieval_plan_id": str(plan_id),
            "retrieval_round": 2,
        },
        knowledge=knowledge,
        access_policy=ProjectAccessPolicy(),
        store=store,
    )

    assert result["route"] == "refusal"
    assert result["last_error_code"] == "RETRIEVAL_ROUND_LIMIT"
    assert knowledge.retrieval_requests == []
    assert store.telemetry[run_id].retrieval_rounds == 0


@pytest.mark.asyncio
async def test_two_round_refinement_preserves_identical_authorization_scope() -> None:
    run_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    version_id = uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "How do I roll back ALPHA?")
    context = AuthorizedProjectContext(
        scope=ProjectAccessScope(
            company_id=uuid4(),
            user_id=user_id,
            allowed_client_ids=(uuid4(),),
            allowed_project_ids=(project_id,),
            allowed_document_version_ids=(version_id,),
            allowed_document_categories=("runbook",),
            role_ids=("developer",),
            policy_version="test",
        ),
        project_code="PRJ-ALPHA",
        knowledge_space_ids=("dataset-alpha",),
    )
    access_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )
    plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=RetrievalPlan(
            original_query="How do I roll back ALPHA?",
            standalone_query="ALPHA rollback",
            exact_identifiers=("ALPHA",),
            identifier_resolutions=(),
            constrained_document_version_ids=(version_id,),
            constrained_provider_document_ids=("provider-doc-1",),
            allowed_categories=("runbook",),
            allow_second_round=True,
        ).model_dump(mode="json"),
    )
    knowledge = FakeKnowledgePort()
    knowledge.add_chunk(
        project_id="PRJ-ALPHA",
        document_version_id=str(version_id),
        knowledge_space_id="dataset-alpha",
        content="authorized evidence",
        score=0.7,
    )
    state = {
        "run_id": str(run_id),
        "user_id": str(user_id),
        "project_id": str(project_id),
        "access_scope_id": str(access_id),
        "retrieval_plan_id": str(plan_id),
        "retrieval_round": 0,
    }

    state.update(
        await retrieve_node(
            state,
            knowledge=knowledge,
            access_policy=ProjectAccessPolicy(),
            store=store,
        )
    )
    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "adequate": False,
            "reason": "INSUFFICIENT_COVERAGE",
            "second_round_justified": True,
            "refined_query": "ALPHA exact rollback procedure",
        }
    )
    state.update(
        await grade_retrieval_node(
            state,
            llm=llm,
            llm_usage=llm,
            store=store,
            model_alias="fake",
        )
    )
    assert state["route"] == "retrieve_again"
    state.update(
        await retrieve_node(
            state,
            knowledge=knowledge,
            access_policy=ProjectAccessPolicy(),
            store=store,
        )
    )

    assert len(knowledge.retrieval_requests) == 2
    first, second = knowledge.retrieval_requests
    assert second.project_id == first.project_id
    assert second.document_version_ids == first.document_version_ids
    assert second.knowledge_space_ids == first.knowledge_space_ids
    assert second.query != first.query
    assert second.query == "ALPHA exact rollback procedure"
    assert state["retrieval_round"] == 2
    assert store.telemetry[run_id].retrieval_rounds == 2
    llm.queue_response(
        {
            "adequate": True,
            "reason": "ADEQUATE",
            "second_round_justified": False,
            "refined_query": None,
        }
    )
    state.update(
        await grade_retrieval_node(
            state,
            llm=llm,
            llm_usage=llm,
            store=store,
            model_alias="fake",
        )
    )
    assert state["route"] == "govern_evidence"


@pytest.mark.asyncio
async def test_second_round_inadequate_grade_refuses_without_third_retrieval() -> None:
    run_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    version_id = uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "Need exact rollback evidence")
    context = AuthorizedProjectContext(
        scope=ProjectAccessScope(
            company_id=uuid4(),
            user_id=user_id,
            allowed_client_ids=(uuid4(),),
            allowed_project_ids=(project_id,),
            allowed_document_version_ids=(version_id,),
            allowed_document_categories=("runbook",),
            role_ids=("developer",),
            policy_version="test",
        ),
        project_code="PRJ-ALPHA",
        knowledge_space_ids=("dataset-alpha",),
    )
    access_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )
    plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=RetrievalPlan(
            original_query="Need exact rollback evidence",
            standalone_query="rollback evidence",
            exact_identifiers=(),
            identifier_resolutions=(),
            constrained_document_version_ids=(version_id,),
            allow_second_round=True,
        ).model_dump(mode="json"),
    )
    knowledge = FakeKnowledgePort()
    knowledge.add_chunk(
        project_id="PRJ-ALPHA",
        document_version_id=str(version_id),
        knowledge_space_id="dataset-alpha",
        content="weak but authorized evidence",
        score=0.4,
    )
    state = {
        "run_id": str(run_id),
        "user_id": str(user_id),
        "project_id": str(project_id),
        "access_scope_id": str(access_id),
        "retrieval_plan_id": str(plan_id),
        "retrieval_round": 0,
    }
    state.update(
        await retrieve_node(
            state, knowledge=knowledge, access_policy=ProjectAccessPolicy(), store=store
        )
    )
    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "adequate": False,
            "reason": "INSUFFICIENT_COVERAGE",
            "second_round_justified": True,
            "refined_query": "exact rollback evidence",
        }
    )
    state.update(
        await grade_retrieval_node(
            state, llm=llm, llm_usage=llm, store=store, model_alias="fake"
        )
    )
    state.update(
        await retrieve_node(
            state, knowledge=knowledge, access_policy=ProjectAccessPolicy(), store=store
        )
    )
    llm.queue_response(
        {
            "adequate": False,
            "reason": "INSUFFICIENT_RELEVANCE",
            "second_round_justified": False,
            "refined_query": None,
        }
    )
    state.update(
        await grade_retrieval_node(
            state, llm=llm, llm_usage=llm, store=store, model_alias="fake"
        )
    )

    assert state["route"] == "refusal"
    assert state["last_error_code"] == "INSUFFICIENT_EVIDENCE"
    assert len(knowledge.retrieval_requests) == 2
    assert state["retrieval_round"] == 2
    assert store.telemetry[run_id].retrieval_rounds == 2
