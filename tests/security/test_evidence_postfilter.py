from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from tests.fakes.authorization import FakeProjectAuthorizationRepository

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
