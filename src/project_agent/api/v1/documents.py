from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from project_agent.application.use_cases.delete_document import DeleteDocumentUseCase
from project_agent.application.use_cases.publish_document import (
    DocumentPublishFailed,
    DocumentPublishPending,
    PublishDocumentUseCase,
)
from project_agent.application.use_cases.review_document import (
    ApproveDocumentUseCase,
    SubmitDocumentReviewUseCase,
)
from project_agent.application.use_cases.upload_document import (
    DocumentActor,
    UploadDocumentCommand,
    UploadDocumentUseCase,
)


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
    document_category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    authority_level: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    owner_user_id: UUID | None = None
    supersedes_version_id: UUID | None = None


router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def _services(request: Request) -> DocumentApiServices:
    services = getattr(request.app.state, "document_api_services", None)
    if not isinstance(services, DocumentApiServices):
        raise HTTPException(status_code=503, detail="document workflow is not configured")
    return services


def _actor(request: Request) -> DocumentActor:
    # Task 9 replaces this injected actor with JWT + database membership authorization.
    actor = getattr(request.state, "document_actor", None)
    if not isinstance(actor, DocumentActor):
        actor = getattr(request.app.state, "document_actor", None)
    if not isinstance(actor, DocumentActor):
        raise HTTPException(status_code=401, detail="document actor is not resolved")
    return actor


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    payload: DocumentUploadRequest,
    request: Request,
    services: DocumentApiServices = Depends(_services),
) -> dict[str, str]:
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid content_base64") from exc
    result = await services.upload.execute(
        UploadDocumentCommand(
            **payload.model_dump(exclude={"content_base64"}),
            data=data,
            actor=_actor(request),
        )
    )
    return {
        "document_id": str(result.document_id),
        "version_id": str(result.version_id),
        "status": result.lifecycle_status.value,
    }


@router.post("/{version_id}/submit-review")
async def submit_review(
    version_id: UUID,
    request: Request,
    services: DocumentApiServices = Depends(_services),
) -> dict[str, str]:
    result = await services.submit_review.execute(version_id, _actor(request))
    return {"version_id": str(result.version_id), "status": result.lifecycle_status.value}


@router.post("/{version_id}/approve")
async def approve_document(
    version_id: UUID,
    request: Request,
    services: DocumentApiServices = Depends(_services),
) -> dict[str, str]:
    result = await services.approve.execute(version_id, _actor(request))
    return {"version_id": str(result.version_id), "status": result.lifecycle_status.value}


@router.post("/{version_id}/publish")
async def publish_document(
    version_id: UUID,
    request: Request,
    services: DocumentApiServices = Depends(_services),
) -> dict[str, str]:
    try:
        result = await services.publish.execute(version_id, _actor(request))
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
    request: Request,
    services: DocumentApiServices = Depends(_services),
) -> dict[str, str]:
    result = await services.delete.execute(version_id, _actor(request))
    return {"version_id": str(result.version_id), "status": result.lifecycle_status.value}
