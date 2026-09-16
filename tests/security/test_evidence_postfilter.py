from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from tests.fakes.authorization import FakeProjectAuthorizationRepository
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.models import RetrievalPlan
from project_agent.agent.nodes.retrieve import retrieve_node
from project_agent.agent.nodes.serialization import serialize_authorized_context
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.application.ports.knowledge import KnowledgeChunk, KnowledgeRetrievalRequest
from project_agent.application.services.authorization import (
    AuthorizationService,
    DocumentAccessRecord,
    MembershipAccessRecord,
)
from project_agent.domain.enums import DocumentCategory, ProjectRole

USER = UUID("11111111-1111-4111-8111-111111111111")
PROJECT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_PROJECT = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
CLIENT = UUID("aaaaaaaa-1111-4111-8111-111111111111")
COMPANY = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
DOC_ALLOWED = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
DOC_OTHER = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
NOW = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)


async def _authorized_context():
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = MembershipAccessRecord(
        company_id=COMPANY,
        client_id=CLIENT,
        project_id=PROJECT,
        project_code="PRJ-ALPHA",
        role=ProjectRole.DEVELOPER,
        valid_from=NOW - timedelta(days=1),
        valid_to=None,
    )
    repo.documents[PROJECT] = [
        DocumentAccessRecord(
            document_version_id=DOC_ALLOWED,
            document_category=DocumentCategory.REQUIREMENT_BASELINE.value,
        )
    ]
    repo.knowledge_spaces[PROJECT] = ("dataset-alpha",)
    return await AuthorizationService(repo, clock=lambda: NOW).authorize_project(
        user_id=USER, project_id=PROJECT
    )


@pytest.mark.asyncio
async def test_retrieval_downpushes_dataset_and_published_document_ids() -> None:
    context = await _authorized_context()
    request = KnowledgeRetrievalRequest(project_id="PRJ-ALPHA", query="REQ-3.2.1")

    constrained = ProjectAccessPolicy().constrain_retrieval(request, context)

    assert constrained is not None
    assert constrained.document_version_ids == (str(DOC_ALLOWED),)
    assert constrained.knowledge_space_ids == ("dataset-alpha",)


@pytest.mark.asyncio
async def test_no_published_documents_means_no_provider_request() -> None:
    repo = FakeProjectAuthorizationRepository()
    repo.memberships[(USER, PROJECT)] = MembershipAccessRecord(
        company_id=COMPANY,
        client_id=CLIENT,
        project_id=PROJECT,
        project_code="PRJ-ALPHA",
        role=ProjectRole.DEVELOPER,
        valid_from=NOW - timedelta(days=1),
        valid_to=None,
    )
    repo.knowledge_spaces[PROJECT] = ("dataset-alpha",)
    context = await AuthorizationService(repo, clock=lambda: NOW).authorize_project(
        user_id=USER, project_id=PROJECT
    )

    constrained = ProjectAccessPolicy().constrain_retrieval(
        KnowledgeRetrievalRequest(project_id="PRJ-ALPHA", query="anything"), context
    )

    assert constrained is None


@pytest.mark.asyncio
async def test_postfilter_drops_cross_project_wrong_version_and_wrong_dataset() -> None:
    context = await _authorized_context()
    chunks = [
        KnowledgeChunk(
            project_id="PRJ-ALPHA",
            document_version_id=str(DOC_ALLOWED),
            knowledge_space_id="dataset-alpha",
            content="allowed",
            score=0.70,
        ),
        KnowledgeChunk(
            project_id="PRJ-BETA",
            document_version_id=str(DOC_OTHER),
            knowledge_space_id="dataset-beta",
            content="cross-project-high-score",
            score=0.99,
        ),
        KnowledgeChunk(
            project_id="PRJ-ALPHA",
            document_version_id=str(DOC_OTHER),
            knowledge_space_id="dataset-alpha",
            content="unpublished-or-unauthorized-version",
            score=0.98,
        ),
        KnowledgeChunk(
            project_id="PRJ-ALPHA",
            document_version_id=str(DOC_ALLOWED),
            knowledge_space_id="dataset-beta",
            content="wrong-dataset",
            score=0.97,
        ),
        KnowledgeChunk(
            project_id="PRJ-ALPHA",
            document_version_id=str(DOC_ALLOWED),
            knowledge_space_id=None,
            content="unverifiable-dataset",
            score=0.96,
        ),
    ]

    filtered = ProjectAccessPolicy().postfilter_evidence(chunks, context)

    assert [chunk.content for chunk in filtered] == ["allowed"]


@pytest.mark.asyncio
async def test_requested_unauthorized_document_or_dataset_never_reaches_provider() -> None:
    context = await _authorized_context()
    policy = ProjectAccessPolicy()

    wrong_document = policy.constrain_retrieval(
        KnowledgeRetrievalRequest(
            project_id="PRJ-ALPHA",
            query="x",
            document_version_ids=(str(DOC_OTHER),),
        ),
        context,
    )
    wrong_dataset = policy.constrain_retrieval(
        KnowledgeRetrievalRequest(
            project_id="PRJ-ALPHA",
            query="x",
            knowledge_space_ids=("dataset-beta",),
        ),
        context,
    )

    assert wrong_document is None
    assert wrong_dataset is None


class _InjectingKnowledgePort:
    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        self.chunks = chunks
        self.requests: list[KnowledgeRetrievalRequest] = []

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> list[KnowledgeChunk]:
        self.requests.append(request)
        return list(self.chunks)


@pytest.mark.asyncio
async def test_postfilter_is_reapplied_on_both_authorized_retrieval_rounds() -> None:
    context = await _authorized_context()
    run_id = UUID("99999999-9999-4999-8999-999999999999")
    store = InMemoryQAGraphStore()
    store.seed_query(run_id, "REQ-3.2.1")
    access_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="PROJECT_ACCESS_SCOPE",
        payload=serialize_authorized_context(context),
    )
    plan = RetrievalPlan(
        original_query="REQ-3.2.1",
        standalone_query="REQ-3.2.1",
        exact_identifiers=("REQ-3.2.1",),
        identifier_resolutions=(),
        constrained_document_version_ids=(DOC_ALLOWED,),
        allow_second_round=True,
    )
    plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=plan.model_dump(mode="json"),
    )
    provider = _InjectingKnowledgePort(
        [
            KnowledgeChunk(
                project_id="PRJ-ALPHA",
                document_version_id=str(DOC_ALLOWED),
                knowledge_space_id="dataset-alpha",
                content="allowed",
                score=0.70,
            ),
            KnowledgeChunk(
                project_id="PRJ-BETA",
                document_version_id=str(DOC_OTHER),
                knowledge_space_id="dataset-beta",
                content="cross-project",
                score=0.99,
            ),
            KnowledgeChunk(
                project_id="PRJ-ALPHA",
                document_version_id=str(DOC_OTHER),
                knowledge_space_id="dataset-alpha",
                content="wrong-version",
                score=0.98,
            ),
            KnowledgeChunk(
                project_id="PRJ-ALPHA",
                document_version_id=str(DOC_ALLOWED),
                knowledge_space_id="dataset-beta",
                content="wrong-space",
                score=0.97,
            ),
        ]
    )
    state = {
        "run_id": str(run_id),
        "project_id": str(PROJECT),
        "access_scope_id": str(access_id),
        "retrieval_plan_id": str(plan_id),
        "retrieval_round": 0,
    }

    first = await retrieve_node(
        state,
        knowledge=provider,
        access_policy=ProjectAccessPolicy(),
        store=store,
    )
    state.update(first)
    refined_plan_id = await store.save_artifact(
        run_id=run_id,
        artifact_type="RETRIEVAL_PLAN",
        payload=plan.model_copy(update={"standalone_query": "REQ-3.2.1 exact"}).model_dump(
            mode="json"
        ),
    )
    state["retrieval_plan_id"] = str(refined_plan_id)
    second = await retrieve_node(
        state,
        knowledge=provider,
        access_policy=ProjectAccessPolicy(),
        store=store,
    )

    for result in (first, second):
        chunks = await store.load_evidence_bundle(UUID(result["evidence_bundle_id"]))
        assert [chunk.content for chunk in chunks] == ["allowed"]
    assert len(provider.requests) == 2
    assert provider.requests[0].project_id == provider.requests[1].project_id == "PRJ-ALPHA"
    assert provider.requests[0].document_version_ids == provider.requests[1].document_version_ids
    assert provider.requests[0].knowledge_space_ids == provider.requests[1].knowledge_space_ids
