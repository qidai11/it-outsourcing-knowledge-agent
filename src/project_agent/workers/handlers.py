from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from project_agent.workers.concurrency import ParseConcurrencyLimiter

JobHandler = Callable[[str], Awaitable[Any]]

INGEST_DOCUMENT = "INGEST_DOCUMENT"
DELETE_DOCUMENT = "DELETE_DOCUMENT"
EXECUTE_AGENT_RUN = "EXECUTE_AGENT_RUN"
RESUME_AGENT_RUN = "RESUME_AGENT_RUN"
RECONCILE_ISSUE_CREATE = "RECONCILE_ISSUE_CREATE"
RETENTION_SWEEP = "RETENTION_SWEEP"

# Compatibility alias retained for the Task 3 contract vocabulary.
DOCUMENT_INGEST = INGEST_DOCUMENT


class UnknownJobType(LookupError):
    pass


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    def resolve(self, job_type: str) -> JobHandler:
        try:
            return self._handlers[job_type]
        except KeyError as exc:
            raise UnknownJobType(job_type) from exc


class ParseLimitedHandler:
    def __init__(self, handler: JobHandler, limiter: ParseConcurrencyLimiter) -> None:
        self._handler = handler
        self._limiter = limiter

    async def __call__(self, aggregate_id: str) -> Any:
        async with self._limiter.slot():
            return await self._handler(aggregate_id)
