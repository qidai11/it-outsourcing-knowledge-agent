from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.citation_guard import citation_guard_node
from project_agent.agent.nodes.models import GroundedAnswerDraft
from project_agent.application.services.citation_guard import CitationGuard
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.evidence import FrozenEvidence, FrozenEvidenceBundle
from project_agent.observability.metrics import ObservabilityMetrics, metrics_context


def _evidence(label: str, project_id: UUID) -> FrozenEvidence:
    return FrozenEvidence(
        snapshot_id=uuid4(),
        label=label,
        project_id=project_id,
        project_code="PRJ-OBS",
        document_version_id=uuid4(),
        document_category=DocumentCategory.REQUIREMENT_BASELINE,
        document_title="Requirement",
        version_no=1,
        version_label="v1",
        authority_level=AuthorityLevel.REQUIREMENT_BASELINE,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        is_current=True,
        effective_from=None,
        effective_to=None,
        content="fact",
        content_hash="hash",
        score=1.0,
        knowledge_space_id="dataset",
        provider_ref="chunk",
        page_no=1,
        section="1",
        conflict_key=None,
        claim_value=None,
        unresolved_conflict=False,
    )


@pytest.mark.asyncio
async def test_citation_node_records_pass_and_revision_outcomes() -> None:
    run_id, project_id = uuid4(), uuid4()
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "q")
    bundle_id = uuid4()
    store.governed_bundles[bundle_id] = FrozenEvidenceBundle(
        evidence=(_evidence("E1", project_id),), unresolved_conflicts={}
    )

    valid_id = uuid4()
    store.artifacts[valid_id] = {
        "run_id": str(run_id),
        "artifact_type": "ANSWER_DRAFT",
        "payload": GroundedAnswerDraft.model_validate(
            {"claims": [{"text": "fact", "evidence_ids": ["E1"]}], "conflict_disclosure": None}
        ).model_dump(),
    }
    metrics = ObservabilityMetrics()
    with metrics_context(metrics):
        result = await citation_guard_node(
            {
                "run_id": str(run_id),
                "project_id": str(project_id),
                "answer_draft_id": str(valid_id),
                "evidence_bundle_id": str(bundle_id),
                "revision_count": 0,
            },
            guard=CitationGuard(),
            store=store,
        )
    assert result["route"] == "answered"

    invalid_id = uuid4()
    store.artifacts[invalid_id] = {
        "run_id": str(run_id),
        "artifact_type": "ANSWER_DRAFT",
        "payload": GroundedAnswerDraft.model_validate(
            {"claims": [{"text": "fact", "evidence_ids": []}], "conflict_disclosure": None}
        ).model_dump(),
    }
    with metrics_context(metrics):
        result = await citation_guard_node(
            {
                "run_id": str(run_id),
                "project_id": str(project_id),
                "answer_draft_id": str(invalid_id),
                "evidence_bundle_id": str(bundle_id),
                "revision_count": 0,
            },
            guard=CitationGuard(),
            store=store,
        )
    assert result["route"] == "revise_answer"

    rendered = metrics.render_latest().decode()
    assert 'project_agent_citation_guard_total{outcome="pass"} 1.0' in rendered
    assert 'project_agent_citation_guard_total{outcome="revision"} 1.0' in rendered
