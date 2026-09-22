from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.api.dependencies import (
    get_api_runtime,
    get_authenticated_identity,
    get_authorization_service,
    get_db_session,
)
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationDenied,
    AuthorizationService,
)
from project_agent.application.services.document_access import (
    AuthorizedDocumentActor,
    DocumentAccessService,
    DocumentOperation,
)
from project_agent.application.use_cases.delete_document import DeleteDocumentUseCase
from project_agent.application.use_cases.publish_document import (
    DocumentPublishFailed,
    DocumentPublishPending,
    PublishDocumentUseCase,
)
from project_agent.application.use_cases.review_document import (
    ApproveDocumentUseCase,
    DocumentPermissionDenied,
    SubmitDocumentReviewUseCase,
)
from project_agent.application.use_cases.upload_document import (
    UploadDocumentCommand,
    UploadDocumentUseCase,
)
from project_agent.domain.enums import AuthorityLevel, DocumentCategory
from project_agent.infrastructure.db.repositories.documents import (
    SqlAlchemyDocumentWorkflowRepository,
)
from project_agent.runtime.api import ApiRuntime


@dataclass(frozen=True, slots=True)
class DocumentApiServices:
    upload: UploadDocumentUseCase
    submit_review: SubmitDocumentReviewUseCase
    approve: ApproveDocumentUseCase
    publish: PublishDocumentUseCase
    delete: DeleteDocumentUseCase


class DocumentUploadRequest(BaseModel):
    company_id: UUID
    project_id: UUID
    document_id: UUID | None = None
    document_category: DocumentCategory
    title: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    authority_level: AuthorityLevel
    filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    owner_user_id: UUID | None = None
    supersedes_version_id: UUID | None = None


router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def get_document_api_services(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    runtime: Annotated[ApiRuntime, Depends(get_api_runtime)],
) -> DocumentApiServices:
    repository = SqlAlchemyDocumentWorkflowRepository(session)
    return DocumentApiServices(
        upload=UploadDocumentUseCase(repository, runtime.object_store),
        submit_review=SubmitDocumentReviewUseCase(repository),
        approve=ApproveDocumentUseCase(repository),
        publish=PublishDocumentUseCase(repository, runtime.knowledge, commit_barrier=session),
        delete=DeleteDocumentUseCase(repository, runtime.knowledge, commit_barrier=session),
    )


def get_document_access_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> DocumentAccessService:
    return DocumentAccessService(
        authorization=authorization,
        repository=SqlAlchemyDocumentWorkflowRepository(session),
    )


def _forbidden(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def _not_found(version_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"document version {version_id} not found",
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    payload: DocumentUploadRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    access: Annotated[DocumentAccessService, Depends(get_document_access_service)],
    services: Annotated[DocumentApiServices, Depends(get_document_api_services)],
) -> dict[str, str]:
    try:
        authorized = await access.authorize_project_operation(
            identity=identity,
            project_id=payload.project_id,
            operation=DocumentOperation.UPLOAD,
            expected_company_id=payload.company_id,
        )
    except AuthorizationDenied as exc:
        raise _forbidden(exc) from exc
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid content_base64") from exc
    result = await services.upload.execute(
        UploadDocumentCommand(
            **payload.model_dump(exclude={"content_base64"}),
            data=data,
            actor=authorized.actor,
        )
    )
    return {
        "document_id": str(result.document_id),
        "version_id": str(result.version_id),
        "status": result.lifecycle_status.value,
    }


async def _authorize_version(
    *,
    access: DocumentAccessService,
    identity: AuthenticatedIdentity,
    version_id: UUID,
    operation: DocumentOperation,
) -> AuthorizedDocumentActor:
    try:
        return await access.authorize_version_operation(
            identity=identity, version_id=version_id, operation=operation
        )
    except (LookupError, KeyError) as exc:
        raise _not_found(version_id) from exc
    except AuthorizationDenied as exc:
        raise _forbidden(exc) from exc


@router.post("/{version_id}/submit-review")
async def submit_review(
    version_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    access: Annotated[DocumentAccessService, Depends(get_document_access_service)],
    services: Annotated[DocumentApiServices, Depends(get_document_api_services)],
) -> dict[str, str]:
    authorized = await _authorize_version(
        access=access,
        identity=identity,
        version_id=version_id,
        operation=DocumentOperation.SUBMIT_REVIEW,
    )
    try:
        result = await services.submit_review.execute(version_id, authorized.actor)
    except DocumentPermissionDenied as exc:
        raise _forbidden(exc) from exc
    return {"version_id": str(result.version_id), "status": result.lifecycle_status.value}


@router.post("/{version_id}/approve")
async def approve_document(
    version_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    access: Annotated[DocumentAccessService, Depends(get_document_access_service)],
    services: Annotated[DocumentApiServices, Depends(get_document_api_services)],
) -> dict[str, str]:
    authorized = await _authorize_version(
        access=access,
        identity=identity,
        version_id=version_id,
        operation=DocumentOperation.APPROVE,
    )
    try:
        result = await services.approve.execute(version_id, authorized.actor)
    except DocumentPermissionDenied as exc:
        raise _forbidden(exc) from exc
    return {"version_id": str(result.version_id), "status": result.lifecycle_status.value}


@router.post("/{version_id}/publish")
async def publish_document(
    version_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    access: Annotated[DocumentAccessService, Depends(get_document_access_service)],
    services: Annotated[DocumentApiServices, Depends(get_document_api_services)],
) -> dict[str, str]:
    authorized = await _authorize_version(
        access=access,
        identity=identity,
        version_id=version_id,
        operation=DocumentOperation.PUBLISH,
    )
    try:
        result = await services.publish.execute(version_id, authorized.actor)
    except DocumentPermissionDenied as exc:
        raise _forbidden(exc) from exc
    except DocumentPublishPending as exc:
        return {
            "version_id": str(version_id),
            "status": "PUBLISH_PENDING",
            "ingestion_job_id": exc.ingestion_job_id,
        }
    except DocumentPublishFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"version_id": str(result.version_id), "status": result.lifecycle_status.value}


@router.delete("/{version_id}")
async def delete_document(
    version_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    access: Annotated[DocumentAccessService, Depends(get_document_access_service)],
    services: Annotated[DocumentApiServices, Depends(get_document_api_services)],
) -> dict[str, str]:
    authorized = await _authorize_version(
        access=access,
        identity=identity,
        version_id=version_id,
        operation=DocumentOperation.ARCHIVE,
    )
    try:
        result = await services.delete.execute(version_id, authorized.actor)
    except DocumentPermissionDenied as exc:
        raise _forbidden(exc) from exc
    return {"version_id": str(result.version_id), "status": result.lifecycle_status.value}
