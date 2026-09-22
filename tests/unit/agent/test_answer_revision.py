from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from tests.fakes.evidence_governance import FakeEvidenceGovernanceRepository
from tests.fakes.llm import FakeStructuredLLM
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.citation_guard import citation_guard_node
from project_agent.agent.nodes.generate_answer import generate_answer_node
from project_agent.agent.nodes.revise_answer import revise_answer_node
from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.application.services.citation_guard import CitationGuard
from project_agent.application.services.evidence_governance import (
    DocumentEvidenceMetadata,
    EvidenceGovernanceService,
)
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus


async def _seed_state():
    run_id = uuid4()
    project_id = uuid4()
    version_id = uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "REQ-3.2.1 的规则是什么？")
    prompt_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROMPT_SNAPSHOT",
        payload={"content": "只基于 Evidence 回答。"},
    )
    repo = FakeEvidenceGovernanceRepository()
    repo.records[version_id] = DocumentEvidenceMetadata(
        document_version_id=version_id,
        document_id=uuid4(),
        project_id=project_id,
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        title="Requirement",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        version_no=2,
        version_label="v2",
        effective_from=None,
        effective_to=None,
        is_current=True,
    )
    pack = await EvidenceGovernanceService(repo, today=lambda: date(2026, 8, 8)).pack(
        project_id=project_id,
        project_code="PRJ-RETAIL-ALPHA",
        chunks=[
            KnowledgeChunk(
                project_id="PRJ-RETAIL-ALPHA",
                document_version_id=str(version_id),
                content="连续登录失败 5 次后锁定账户 30 分钟。",
                score=0.9,
                knowledge_space_id="dataset-alpha",
                provider_ref="chunk-1",
            )
        ],
    )
    bundle_id = await store.save_governed_evidence_bundle(
        run_id=run_id,
        project_id=project_id,
        query_text="REQ-3.2.1 的规则是什么？",
        pack=pack,
    )
    return store, {
        "run_id": str(run_id),
        "project_id": str(project_id),
        "prompt_snapshot_id": str(prompt_id),
        "evidence_bundle_id": str(bundle_id),
        "revision_count": 0,
    }


@pytest.mark.asyncio
async def test_answer_generation_requires_at_least_one_evidence_id_per_claim() -> None:
    store, state = await _seed_state()
    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "claims": [{"text": "连续登录失败后会锁定账户。"}],
            "conflict_disclosure": None,
        }
    )

    with pytest.raises(ValidationError):
        await generate_answer_node(
            state,
            llm=llm,
            llm_usage=llm,
            store=store,
            model_alias="fake",
        )


@pytest.mark.asyncio
async def test_answer_generation_rejects_empty_evidence_ids_per_claim() -> None:
    store, state = await _seed_state()
    llm = FakeStructuredLLM()
    llm.queue_response(
        {
            "claims": [{"text": "连续登录失败后会锁定账户。", "evidence_ids": []}],
            "conflict_disclosure": None,
        }
    )

    with pytest.raises(ValidationError):
        await generate_answer_node(
            state,
            llm=llm,
            llm_usage=llm,
            store=store,
            model_alias="fake",
        )


@pytest.mark.asyncio
async def test_one_invalid_draft_can_be_revised_once_then_persisted_with_citation() -> None:
    store, state = await _seed_state()
    llm = FakeStructuredLLM()
    llm.queue_response({
        "claims": [{"text": "锁定 30 分钟。", "evidence_ids": ["E99"]}],
        "conflict_disclosure": None,
    }, input_tokens=20, output_tokens=10)
    llm.queue_response({
        "claims": [{"text": "连续登录失败 5 次后锁定账户 30 分钟。", "evidence_ids": ["E1"]}],
        "conflict_disclosure": None,
    }, input_tokens=25, output_tokens=12)

    first = await generate_answer_node(
        state, llm=llm, llm_usage=llm, store=store, model_alias="fake"
    )
    state.update(first)
    checked = await citation_guard_node(state, guard=CitationGuard(), store=store)
    assert checked["route"] == "revise_answer"
    state.update(checked)

    revised = await revise_answer_node(
        state, llm=llm, llm_usage=llm, store=store, model_alias="fake"
    )
    state.update(revised)
    assert state["revision_count"] == 1
    checked = await citation_guard_node(state, guard=CitationGuard(), store=store)

    assert checked["route"] == "answered"
    answer_id = UUID(checked["answer_id"])
    assert store.answers[answer_id]["answer_text"] == "连续登录失败 5 次后锁定账户 30 分钟。 [E1]"
    assert len(store.citations[answer_id]) == 1
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_second_invalid_draft_stops_after_one_revision() -> None:
    store, state = await _seed_state()
    llm = FakeStructuredLLM()
    invalid = {
        "claims": [{"text": "无依据。", "evidence_ids": ["E99"]}],
        "conflict_disclosure": None,
    }
    llm.queue_response(invalid)
    llm.queue_response(invalid)

    state.update(
        await generate_answer_node(
            state, llm=llm, llm_usage=llm, store=store, model_alias="fake"
        )
    )
    state.update(await citation_guard_node(state, guard=CitationGuard(), store=store))
    state.update(
        await revise_answer_node(
            state, llm=llm, llm_usage=llm, store=store, model_alias="fake"
        )
    )
    checked = await citation_guard_node(state, guard=CitationGuard(), store=store)

    assert checked["route"] == "refusal"
    assert checked["last_error_code"] == "CITATION_GUARD_FAILED"
    assert len(llm.calls) == 2

@pytest.mark.asyncio
async def test_citation_persistence_keeps_original_evidence_number() -> None:
    store, state = await _seed_state()
    bundle_id = UUID(state["evidence_bundle_id"])
    original = store.governed_bundles[bundle_id]
    from dataclasses import replace

    from project_agent.domain.evidence import FrozenEvidenceBundle

    e1 = original.evidence[0]
    e2 = replace(e1, snapshot_id=uuid4(), label="E2", content="第二条证据")
    store.governed_bundles[bundle_id] = FrozenEvidenceBundle(
        evidence=(e1, e2), unresolved_conflicts={}
    )
    llm = FakeStructuredLLM()
    llm.queue_response({
        "claims": [{"text": "第二条事实。", "evidence_ids": ["E2"]}],
        "conflict_disclosure": None,
    })
    state.update(await generate_answer_node(
        state, llm=llm, llm_usage=llm, store=store, model_alias="fake"
    ))
    checked = await citation_guard_node(state, guard=CitationGuard(), store=store)
    answer_id = UUID(checked["answer_id"])

    assert store.citations[answer_id][0].citation_no == 2
