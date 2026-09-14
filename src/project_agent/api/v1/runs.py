from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.api.dependencies import (
    get_authenticated_identity,
    get_authorization_service,
    get_db_session,
)
from project_agent.application.ports.run_repository import RunRepository
from project_agent.application.services.authorization import (
    AuthenticatedIdentity,
    AuthorizationDenied,
    AuthorizationService,
)
from project_agent.application.services.runs import (
    CreateRunCommand,
    RunAccessDenied,
    RunApplicationService,
    RunNotFound,
    ThreadNotFound,
)
from project_agent.domain.runs import RunBusinessMode, RunRecord, RunStatus
from project_agent.infrastructure.db.repositories.runs import SqlAlchemyRunRepository
from project_agent.infrastructure.jobs.postgres import SqlAlchemySessionJobEnqueuer


class CreateRunRequest(BaseModel):
    project_id: UUID
    business_mode: RunBusinessMode
    query: str = Field(min_length=1)
    thread_id: UUID | None = None


class RunResponse(BaseModel):
    run_id: UUID
    thread_id: UUID
    project_id: UUID
    business_mode: RunBusinessMode
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    result_ref: str | None = None
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class RunApiServices:
    runs: RunApplicationService
    repository: RunRepository


router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def get_run_api_services(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> RunApiServices:
    repository = SqlAlchemyRunRepository(session)
    jobs = SqlAlchemySessionJobEnqueuer(session)
    return RunApiServices(
        runs=RunApplicationService(
            authorization=authorization,
            repository=repository,
            jobs=jobs,
        ),
        repository=repository,
    )


def _forbidden(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _response(run: RunRecord) -> RunResponse:
    return RunResponse(
        run_id=run.id,
        thread_id=run.thread_id,
        project_id=run.project_id,
        business_mode=run.business_mode,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        result_ref=run.result_ref,
        summary=run.result_summary,
    )


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: CreateRunRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    services: Annotated[RunApiServices, Depends(get_run_api_services)],
) -> RunResponse:
    try:
        run = await services.runs.create_run(
            identity=identity,
            command=CreateRunCommand(
                project_id=payload.project_id,
                business_mode=payload.business_mode,
                query_text=payload.query,
                thread_id=payload.thread_id,
            ),
        )
    except (AuthorizationDenied, RunAccessDenied) as exc:
        raise _forbidden(exc) from exc
    except (RunNotFound, ThreadNotFound) as exc:
        raise _not_found(exc) from exc
    return _response(run)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    services: Annotated[RunApiServices, Depends(get_run_api_services)],
) -> RunResponse:
    try:
        run = await services.runs.get_run(identity=identity, run_id=run_id)
    except (AuthorizationDenied, RunAccessDenied) as exc:
        raise _forbidden(exc) from exc
    except (RunNotFound, ThreadNotFound) as exc:
        raise _not_found(exc) from exc
    return _response(run)
