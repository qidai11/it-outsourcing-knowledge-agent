from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from project_agent.application.ports.knowledge import IngestionState
from project_agent.domain.metadata import MetadataSuggestion
from project_agent.application.use_cases.delete_document import DeleteDocumentUseCase
from project_agent.application.use_cases.publish_document import (
    DocumentPublishFailed,
    PublishDocumentUseCase,
)
from project_agent.application.use_cases.review_document import (
    ApproveDocumentUseCase,
    DocumentPermissionDenied,
    SubmitDocumentReviewUseCase,
)
from project_agent.application.use_cases.upload_document import (
    DocumentActor,
    UploadDocumentCommand,
    UploadDocumentUseCase,
)
from project_agent.domain.enums import DocumentLifecycleStatus
from tests.fakes.document_repository import InMemoryDocumentWorkflowRepository
from tests.fakes.knowledge import FakeKnowledgePort
from tests.fakes.object_store import InMemoryObjectStore


def actor(user_id: UUID, *, permissions: set[str] | None = None) -> DocumentActor:
    return DocumentActor(
        user_id=user_id,
        permissions=frozenset(permissions or set()),
    )


@pytest.mark.asyncio
async def test_upload_requires_human_confirmed_metadata_and_creates_draft() -> None:
    repository = InMemoryDocumentWorkflowRepository()
    object_store = InMemoryObjectStore()
    uploader_id = uuid4()
    project_id = uuid4()
    company_id = uuid4()
    use_case = UploadDocumentUseCase(repository, object_store)

    with pytest.raises(ValidationError):
        UploadDocumentCommand(  # type: ignore[call-arg]
            company_id=company_id,
            project_id=project_id,
            title="Order requirements",
            filename="requirements.pdf",
            data=b"pdf-bytes",
            mime_type="application/pdf",
            owner_user_id=uuid4(),
            actor=actor(uploader_id),
        )

    result = await use_case.execute(
        UploadDocumentCommand(
            company_id=company_id,
            project_id=project_id,
            document_category="requirement_baseline",
            title="Order requirements",
            version_label="v2.1",
            authority_level="requirement_baseline",
            filename="requirements.pdf",
            data=b"pdf-bytes",
            mime_type="application/pdf",
            owner_user_id=uuid4(),
            actor=actor(uploader_id),
        )
    )

    assert result.lifecycle_status is DocumentLifecycleStatus.DRAFT
    assert result.created_by == uploader_id
    assert result.document_category == "requirement_baseline"
    assert result.authority_level == "requirement_baseline"
    assert result.source_uri.startswith("objects/") or result.source_uri.startswith("projects/")


@pytest.mark.asyncio
async def test_human_final_metadata_overrides_suggestion_and_is_audited() -> None:
    repository = InMemoryDocumentWorkflowRepository()
    object_store = InMemoryObjectStore()
    uploader_id = uuid4()
    project_id = uuid4()
    owner_id = uuid4()
    suggestion = MetadataSuggestion(
        suggested_project_id=project_id,
        suggested_document_category="api_specification",
        suggested_version_label="v9.9",
        suggested_authority_level="approved_design",
        confidence=0.95,
        evidence=("test suggestion",),
    )
    use_case = UploadDocumentUseCase(repository, object_store)

    result = await use_case.execute(
        UploadDocumentCommand(
            company_id=uuid4(),
            project_id=project_id,
            document_category="requirement_baseline",
            title="Human selected title",
            version_label="v2.1",
            authority_level="requirement_baseline",
            filename="ambiguous.pdf",
            data=b"content",
            mime_type="application/pdf",
            owner_user_id=owner_id,
            actor=actor(uploader_id),
            suggestion=suggestion,
        )
    )

    assert result.document_category == "requirement_baseline"
    assert result.version_label == "v2.1"
    assert result.authority_level == "requirement_baseline"

    audit = repository.audits[-1]
    assert audit.action == "document_metadata_confirmed"
    assert audit.user_id == uploader_id
    assert audit.details["suggestion"]["suggested_document_category"] == "api_specification"
    assert audit.details["final"]["document_category"] == "requirement_baseline"
    assert audit.details["final"]["authority_level"] == "requirement_baseline"


@pytest.mark.asyncio
async def test_owner_approves_and_only_authorized_actor_publishes() -> None:
    repository = InMemoryDocumentWorkflowRepository()
    object_store = InMemoryObjectStore()
    knowledge = FakeKnowledgePort()
    owner_id = uuid4()
    uploader_id = uuid4()
    publisher_id = uuid4()
    project_id = uuid4()
    repository.bind_knowledge_space(project_id, "ks-alpha")

    draft = await UploadDocumentUseCase(repository, object_store).execute(
        UploadDocumentCommand(
            company_id=uuid4(),
            project_id=project_id,
            document_category="approved_design",
            title="Design",
            version_label="v1.0",
            authority_level="approved_design",
            filename="design.md",
            data=b"design",
            mime_type="text/markdown",
            owner_user_id=owner_id,
            actor=actor(uploader_id),
        )
    )

    under_review = await SubmitDocumentReviewUseCase(repository).execute(
        draft.version_id, actor(uploader_id)
    )
    assert under_review.lifecycle_status is DocumentLifecycleStatus.UNDER_REVIEW

    with pytest.raises(DocumentPermissionDenied):
        await ApproveDocumentUseCase(repository).execute(
            draft.version_id,
            actor(uploader_id),
        )

    approved = await ApproveDocumentUseCase(repository).execute(
        draft.version_id,
        actor(owner_id),
    )
    assert approved.lifecycle_status is DocumentLifecycleStatus.APPROVED

    with pytest.raises(DocumentPermissionDenied):
        await PublishDocumentUseCase(repository, knowledge).execute(
            draft.version_id,
            actor(owner_id),
        )

    published = await PublishDocumentUseCase(repository, knowledge).execute(
        draft.version_id,
        actor(publisher_id, permissions={"publish_document"}),
    )
    assert published.lifecycle_status is DocumentLifecycleStatus.PUBLISHED


@pytest.mark.asyncio
async def test_failed_new_version_publish_keeps_old_version_published() -> None:
    repository = InMemoryDocumentWorkflowRepository()
    object_store = InMemoryObjectStore()
    knowledge = FakeKnowledgePort()
    project_id = uuid4()
    owner_id = uuid4()
    publisher_id = uuid4()
    repository.bind_knowledge_space(project_id, "ks-alpha")

    old = repository.seed_version(
        company_id=uuid4(),
        project_id=project_id,
        document_category="requirement_baseline",
        title="Requirements",
        version_label="v2.0",
        authority_level="requirement_baseline",
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        owner_user_id=owner_id,
    )

    new = await UploadDocumentUseCase(repository, object_store).execute(
        UploadDocumentCommand(
            company_id=old.company_id,
            project_id=project_id,
            document_id=old.document_id,
            document_category="requirement_baseline",
            title="Requirements",
            version_label="v2.1",
            authority_level="requirement_baseline",
            filename="requirements-v2.1.pdf",
            data=b"new",
            mime_type="application/pdf",
            owner_user_id=owner_id,
            supersedes_version_id=old.version_id,
            actor=actor(uuid4()),
        )
    )
    await SubmitDocumentReviewUseCase(repository).execute(new.version_id, actor(new.created_by))
    await ApproveDocumentUseCase(repository).execute(new.version_id, actor(owner_id))

    knowledge.next_ingestion_state = IngestionState.FAILED
    with pytest.raises(DocumentPublishFailed):
        await PublishDocumentUseCase(repository, knowledge).execute(
            new.version_id,
            actor(publisher_id, permissions={"publish_document"}),
        )

    assert repository.get_now(old.version_id).lifecycle_status is DocumentLifecycleStatus.PUBLISHED
    assert repository.get_now(new.version_id).lifecycle_status is DocumentLifecycleStatus.APPROVED


@pytest.mark.asyncio
async def test_successful_new_version_publish_supersedes_old_only_after_ingestion_success() -> None:
    repository = InMemoryDocumentWorkflowRepository()
    object_store = InMemoryObjectStore()
    knowledge = FakeKnowledgePort()
    project_id = uuid4()
    owner_id = uuid4()
    publisher_id = uuid4()
    repository.bind_knowledge_space(project_id, "ks-alpha")

    old = repository.seed_version(
        company_id=uuid4(),
        project_id=project_id,
        document_category="requirement_baseline",
        title="Requirements",
        version_label="v2.0",
        authority_level="requirement_baseline",
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        owner_user_id=owner_id,
    )
    new = await UploadDocumentUseCase(repository, object_store).execute(
        UploadDocumentCommand(
            company_id=old.company_id,
            project_id=project_id,
            document_id=old.document_id,
            document_category="requirement_baseline",
            title="Requirements",
            version_label="v2.1",
            authority_level="requirement_baseline",
            filename="requirements-v2.1.pdf",
            data=b"new",
            mime_type="application/pdf",
            owner_user_id=owner_id,
            supersedes_version_id=old.version_id,
            actor=actor(uuid4()),
        )
    )
    await SubmitDocumentReviewUseCase(repository).execute(new.version_id, actor(new.created_by))
    await ApproveDocumentUseCase(repository).execute(new.version_id, actor(owner_id))

    published = await PublishDocumentUseCase(repository, knowledge).execute(
        new.version_id,
        actor(publisher_id, permissions={"publish_document"}),
    )

    assert published.lifecycle_status is DocumentLifecycleStatus.PUBLISHED
    assert repository.get_now(old.version_id).lifecycle_status is DocumentLifecycleStatus.SUPERSEDED


@pytest.mark.asyncio
async def test_delete_pending_precedes_provider_cleanup_and_survives_cleanup_failure() -> None:
    repository = InMemoryDocumentWorkflowRepository()
    knowledge = FakeKnowledgePort()
    project_id = uuid4()
    owner_id = uuid4()
    repository.bind_knowledge_space(project_id, "ks-alpha")
    version = repository.seed_version(
        company_id=uuid4(),
        project_id=project_id,
        document_category="issue_record",
        title="Legacy issue",
        version_label="legacy",
        authority_level="issue_record",
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        owner_user_id=owner_id,
    )
    knowledge.fail_delete = True

    with pytest.raises(RuntimeError, match="simulated knowledge delete failure"):
        await DeleteDocumentUseCase(repository, knowledge).execute(
            version.version_id,
            actor(uuid4(), permissions={"archive_document"}),
        )

    after = repository.get_now(version.version_id)
    assert after.lifecycle_status is DocumentLifecycleStatus.DELETE_PENDING
    assert not after.lifecycle_status.is_online_retrievable


@pytest.mark.asyncio
async def test_pending_publication_can_finalize_without_reingesting() -> None:
    from project_agent.application.use_cases.publish_document import DocumentPublishPending

    repository = InMemoryDocumentWorkflowRepository()
    object_store = InMemoryObjectStore()
    knowledge = FakeKnowledgePort()
    project_id = uuid4()
    owner_id = uuid4()
    publisher = actor(uuid4(), permissions={"publish_document"})
    repository.bind_knowledge_space(project_id, "ks-alpha")

    draft = await UploadDocumentUseCase(repository, object_store).execute(
        UploadDocumentCommand(
            company_id=uuid4(),
            project_id=project_id,
            document_category="release_runbook",
            title="Release Runbook",
            version_label="v1.0",
            authority_level="release_runbook",
            filename="release-v1.0.md",
            data=b"release",
            mime_type="text/markdown",
            owner_user_id=owner_id,
            actor=actor(uuid4()),
        )
    )
    await SubmitDocumentReviewUseCase(repository).execute(
        draft.version_id, actor(draft.created_by)
    )
    await ApproveDocumentUseCase(repository).execute(draft.version_id, actor(owner_id))

    knowledge.next_ingestion_state = IngestionState.RUNNING
    use_case = PublishDocumentUseCase(repository, knowledge)
    with pytest.raises(DocumentPublishPending) as pending:
        await use_case.execute(draft.version_id, publisher)

    assert len(knowledge.ingested_requests) == 1
    knowledge.set_ingestion_state(pending.value.ingestion_job_id, IngestionState.SUCCEEDED)
    published = await use_case.finalize(
        draft.version_id,
        pending.value.ingestion_job_id,
        publisher,
    )

    assert published.lifecycle_status is DocumentLifecycleStatus.PUBLISHED
    assert len(knowledge.ingested_requests) == 1
