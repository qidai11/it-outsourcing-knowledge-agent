from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytest.importorskip("langgraph", reason="Task 10 LangGraph runtime dependency is not installed")

from project_agent.agent.graph import QAGraphDependencies, build_project_qa_graph
from project_agent.agent.nodes.analyze_query import QueryAnalysisService
from project_agent.agent.nodes.resolve_identifiers import ExactIdentifierResolver
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.application.services.citation_guard import CitationGuard
from project_agent.application.services.evidence_governance import DocumentEvidenceMetadata, EvidenceGovernanceService
from project_agent.application.services.authorization import (
    AuthorizationService,
    DocumentAccessRecord,
    MembershipAccessRecord,
)
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.application.services.identifier_registry import IdentifierRegistryService
from project_agent.application.services.prompt_config import PromptConfigRecord, PromptConfigService
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus, ProjectRole
from project_agent.domain.identifiers import IdentifierRegistryEntry, IdentifierSource, IdentifierType
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.evidence_governance import FakeEvidenceGovernanceRepository
from tests.fakes.identifiers import FakeIdentifierRegistryRepository
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.llm import FakeStructuredLLM
from tests.fakes.prompt_config import FakePromptConfigRepository
from tests.fakes.qa_graph_store import InMemoryQAGraphStore


@pytest.fixture
def qa_fixture():
    now = datetime(2026, 8, 8, tzinfo=UTC)
    user_id = uuid4()
    company_id = uuid4()
    alpha_client_id = uuid4()
    beta_client_id = uuid4()
    alpha_project_id = uuid4()
    beta_project_id = uuid4()
    alpha_version = uuid4()
    beta_version = uuid4()

    auth_repo = FakeProjectAuthorizationRepository()
    auth_repo.memberships[(user_id, alpha_project_id)] = MembershipAccessRecord(
        company_id=company_id,
        client_id=alpha_client_id,
        project_id=alpha_project_id,
        project_code="PRJ-RETAIL-ALPHA",
        role=ProjectRole.DEVELOPER,
        valid_from=now - timedelta(days=30),
        valid_to=None,
    )
    auth_repo.memberships[(user_id, beta_project_id)] = MembershipAccessRecord(
        company_id=company_id,
        client_id=beta_client_id,
        project_id=beta_project_id,
        project_code="PRJ-LOGISTICS-BETA",
        role=ProjectRole.DEVELOPER,
        valid_from=now - timedelta(days=30),
        valid_to=None,
    )
    auth_repo.documents[alpha_project_id] = [
        DocumentAccessRecord(
            document_version_id=alpha_version,
            document_category="requirement_baseline",
        )
    ]
    auth_repo.documents[beta_project_id] = [
        DocumentAccessRecord(
            document_version_id=beta_version,
            document_category="requirement_baseline",
        )
    ]
    auth_repo.knowledge_spaces[alpha_project_id] = ("dataset-alpha",)
    auth_repo.knowledge_spaces[beta_project_id] = ("dataset-beta",)

    id_repo = FakeIdentifierRegistryRepository()
    id_repo.entries.extend(
        [
            IdentifierRegistryEntry(
                id=uuid4(),
                company_id=company_id,
                project_id=alpha_project_id,
                document_version_id=alpha_version,
                identifier_type=IdentifierType.REQUIREMENT_ID,
                normalized_value="REQ-3.2.1",
                raw_value="REQ-3.2.1",
                source=IdentifierSource.REGEX,
                confidence=1.0,
            ),
            IdentifierRegistryEntry(
                id=uuid4(),
                company_id=company_id,
                project_id=beta_project_id,
                document_version_id=beta_version,
                identifier_type=IdentifierType.REQUIREMENT_ID,
                normalized_value="REQ-3.2.1",
                raw_value="REQ-3.2.1",
                source=IdentifierSource.REGEX,
                confidence=1.0,
            ),
        ]
    )

    knowledge = FakeKnowledgePort()
    knowledge.add_chunk(
        project_id="PRJ-RETAIL-ALPHA",
        document_version_id=str(alpha_version),
        knowledge_space_id="dataset-alpha",
        content="REQ-3.2.1 要求连续登录失败 5 次后锁定账户 30 分钟。",
        score=0.81,
        provider_ref="alpha-chunk-1",
    )
    knowledge.add_chunk(
        project_id="PRJ-LOGISTICS-BETA",
        document_version_id=str(beta_version),
        knowledge_space_id="dataset-beta",
        content="Beta 项目的 REQ-3.2.1 是物流导入要求。",
        score=0.99,
        provider_ref="beta-chunk-1",
    )

    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "claims": [
                {
                    "text": "连续登录失败 5 次后锁定账户 30 分钟。",
                    "evidence_ids": ["E1"],
                }
            ],
            "conflict_disclosure": None,
        },
        input_tokens=120,
        output_tokens=18,
    )
    prompt_repo = FakePromptConfigRepository(
        PromptConfigRecord(
            config_key="prompt.qa.answer",
            content="只能基于授权 Evidence 回答；没有证据就拒答。",
            version=3,
            content_hash="sha256-prompt-v3",
        )
    )
    evidence_repo = FakeEvidenceGovernanceRepository()
    evidence_repo.records[alpha_version] = DocumentEvidenceMetadata(
        document_version_id=alpha_version,
        document_id=uuid4(),
        project_id=alpha_project_id,
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        title="Alpha Requirement",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        version_no=2,
        version_label="v2.1",
        effective_from=None,
        effective_to=None,
        is_current=True,
    )
    evidence_repo.records[beta_version] = DocumentEvidenceMetadata(
        document_version_id=beta_version,
        document_id=uuid4(),
        project_id=beta_project_id,
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        title="Beta Requirement",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        version_no=1,
        version_label="v1.6",
        effective_from=None,
        effective_to=None,
        is_current=True,
    )
    run_store = InMemoryQAGraphStore()
    deps = QAGraphDependencies(
        authorization=AuthorizationService(auth_repo, clock=lambda: now),
        query_analysis=QueryAnalysisService(IdentifierExtractor()),
        exact_resolver=ExactIdentifierResolver(
            IdentifierRegistryService(id_repo, IdentifierExtractor())
        ),
        knowledge=knowledge,
        access_policy=ProjectAccessPolicy(),
        prompt_config=PromptConfigService(prompt_repo, ttl_seconds=30),
        evidence_governance=EvidenceGovernanceService(evidence_repo, today=lambda: now.date()),
        citation_guard=CitationGuard(),
        llm=llm,
        llm_usage=llm,
        store=run_store,
        model_alias="fake-qa-model",
    )
    return {
        "deps": deps,
        "store": run_store,
        "knowledge": knowledge,
        "llm": llm,
        "user_id": user_id,
        "alpha_project_id": alpha_project_id,
        "alpha_version": alpha_version,
    }


@pytest.mark.asyncio
async def test_exact_identifier_qa_is_project_scoped_and_records_prompt_usage(qa_fixture) -> None:
    run_id = uuid4()
    thread_id = uuid4()
    store = qa_fixture["store"]
    store.seed_query(run_id, "PRJ-RETAIL-ALPHA 的 REQ-3.2.1 要求是什么？")
    graph = build_project_qa_graph(qa_fixture["deps"])

    result = await graph.ainvoke(
        {
            "run_id": str(run_id),
            "thread_id": str(thread_id),
            "user_id": str(qa_fixture["user_id"]),
            "project_id": None,
            "route": None,
            "last_error_code": None,
        },
        config={"configurable": {"thread_id": str(thread_id)}},
    )

    answer_id = result["answer_id"]
    assert store.answers[__import__("uuid").UUID(answer_id)]["answer_text"] == (
        "连续登录失败 5 次后锁定账户 30 分钟。 [E1]"
    )
    assert len(store.citations[__import__("uuid").UUID(answer_id)]) == 1
    assert len(qa_fixture["knowledge"].retrieval_requests) == 1
    retrieval = qa_fixture["knowledge"].retrieval_requests[0]
    assert retrieval.project_id == "PRJ-RETAIL-ALPHA"
    assert retrieval.document_version_ids == (str(qa_fixture["alpha_version"]),)
    assert retrieval.knowledge_space_ids == ("dataset-alpha",)
    telemetry = store.telemetry[run_id]
    assert telemetry.prompt_version == "3"
    assert telemetry.prompt_content_hash == "sha256-prompt-v3"
    assert telemetry.input_tokens == 120
    assert telemetry.output_tokens == 18
    assert telemetry.retrieval_rounds == 1
    assert "query_text" not in result
    assert "evidence" not in result
    assert "answer_text" not in result


@pytest.mark.asyncio
async def test_missing_project_with_multiple_memberships_requires_clarification(qa_fixture) -> None:
    run_id = uuid4()
    thread_id = uuid4()
    store = qa_fixture["store"]
    store.seed_query(run_id, "连续登录失败多少次后锁定？")
    graph = build_project_qa_graph(qa_fixture["deps"])

    result = await graph.ainvoke(
        {
            "run_id": str(run_id),
            "thread_id": str(thread_id),
            "user_id": str(qa_fixture["user_id"]),
            "project_id": None,
            "route": None,
            "last_error_code": None,
        },
        config={"configurable": {"thread_id": str(thread_id)}},
    )

    assert result["route"] == "clarification"
    answer = store.answers[__import__("uuid").UUID(result["answer_id"])]
    assert "项目" in str(answer["answer_text"])
    assert qa_fixture["knowledge"].retrieval_requests == []
    assert qa_fixture["llm"].calls == []


@pytest.mark.asyncio
async def test_no_authorized_evidence_refuses_without_calling_llm(qa_fixture) -> None:
    run_id = uuid4()
    thread_id = uuid4()
    store = qa_fixture["store"]
    store.seed_query(run_id, "PRJ-RETAIL-ALPHA 的 REQ-9.9.9 是什么？")
    qa_fixture["knowledge"]._chunks.clear()
    qa_fixture["llm"]._responses.clear()
    graph = build_project_qa_graph(qa_fixture["deps"])

    result = await graph.ainvoke(
        {
            "run_id": str(run_id),
            "thread_id": str(thread_id),
            "user_id": str(qa_fixture["user_id"]),
            "project_id": None,
            "route": None,
            "last_error_code": None,
        },
        config={"configurable": {"thread_id": str(thread_id)}},
    )

    assert result["route"] == "refusal"
    answer = store.answers[__import__("uuid").UUID(result["answer_id"])]
    assert answer["refusal_reason"] == "NO_AUTHORIZED_EVIDENCE"
    assert qa_fixture["llm"].calls == []
