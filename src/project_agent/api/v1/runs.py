from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

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
    ResumeInputMismatch,
    ResumeRunCommand,
    RunAccessDenied,
    RunApplicationService,
    RunNotFound,
    RunStateConflict,
    ThreadNotFound,
)
from project_agent.domain.issues import ConfirmationAction
from project_agent.domain.runs import (
    TERMINAL_EVENT_TYPES,
    TERMINAL_RUN_STATUSES,
    AgentEventRecord,
    RunBusinessMode,
    RunRecord,
    RunStatus,
)
from project_agent.infrastructure.db.repositories.runs import SqlAlchemyRunRepository
from project_agent.infrastructure.jobs.postgres import SqlAlchemySessionJobEnqueuer
from project_agent.observability.logging import bind_log_context


class CreateRunRequest(BaseModel):
    project_id: UUID
    business_mode: RunBusinessMode
    query: str = Field(min_length=1)
    thread_id: UUID | None = None


class ResumeRunRequest(BaseModel):
    action: ConfirmationAction
    request_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


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


type SleepFn = Callable[[float], Awaitable[None]]


def parse_last_event_id(value: str | None) -> int:
    if value is None or value == "":
        return 0
    if not value.isascii() or not value.isdigit():
        raise ValueError("invalid Last-Event-ID")
    return int(value, 10)


def encode_sse_event(event: AgentEventRecord) -> str:
    payload = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))
    return (
        f"id: {event.sequence_no}\n"
        f"event: {event.event_type.value}\n"
        f"data: {payload}\n\n"
    )


async def iter_sse_events(
    *,
    repository: RunRepository,
    run_id: UUID,
    after_sequence: int,
    poll_seconds: float = 0.25,
    sleep: SleepFn = asyncio.sleep,
) -> AsyncIterator[str]:
    cursor = after_sequence
    while True:
        events = await repository.list_events_after(
            run_id=run_id,
            after_sequence=cursor,
            limit=100,
        )
        for event in events:
            yield encode_sse_event(event)
            cursor = event.sequence_no
            if event.event_type in TERMINAL_EVENT_TYPES:
                return

        if events:
            continue

        run = await repository.get_run(run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return
        await sleep(poll_seconds)


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
    bind_log_context(project_id=str(payload.project_id), business_mode=payload.business_mode.value)
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


@router.post(
    "/{run_id}/resume",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_run(
    run_id: UUID,
    payload: ResumeRunRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    services: Annotated[RunApiServices, Depends(get_run_api_services)],
) -> RunResponse:
    bind_log_context(run_id=str(run_id))
    try:
        run = await services.runs.resume_run(
            identity=identity,
            run_id=run_id,
            command=ResumeRunCommand(
                action=payload.action,
                request_payload_hash=payload.request_payload_hash,
            ),
        )
    except (AuthorizationDenied, RunAccessDenied) as exc:
        raise _forbidden(exc) from exc
    except RunNotFound as exc:
        raise _not_found(exc) from exc
    except (ResumeInputMismatch, RunStateConflict) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return _response(run)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    services: Annotated[RunApiServices, Depends(get_run_api_services)],
) -> RunResponse:
    bind_log_context(run_id=str(run_id))
    try:
        run = await services.runs.get_run(identity=identity, run_id=run_id)
    except (AuthorizationDenied, RunAccessDenied) as exc:
        raise _forbidden(exc) from exc
    except (RunNotFound, ThreadNotFound) as exc:
        raise _not_found(exc) from exc
    return _response(run)


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    services: Annotated[RunApiServices, Depends(get_run_api_services)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    bind_log_context(run_id=str(run_id))
    try:
        after_sequence = parse_last_event_id(last_event_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid Last-Event-ID",
        ) from exc

    try:
        await services.runs.get_run(identity=identity, run_id=run_id)
    except (AuthorizationDenied, RunAccessDenied) as exc:
        raise _forbidden(exc) from exc
    except (RunNotFound, ThreadNotFound) as exc:
        raise _not_found(exc) from exc

    return StreamingResponse(
        iter_sse_events(
            repository=services.repository,
            run_id=run_id,
            after_sequence=after_sequence,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
