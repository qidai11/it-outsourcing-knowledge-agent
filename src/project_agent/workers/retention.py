from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from project_agent.application.ports.job_queue import QueuedJob


@dataclass(frozen=True, slots=True)
class RetentionCandidate:
    resource_type: str
    resource_id: str
    lifecycle_status: str
    legal_hold: bool


class RetentionRepository(Protocol):
    async def list_candidates(self, policy_id: str) -> list[RetentionCandidate]: ...

    async def delete_candidate(self, candidate: RetentionCandidate) -> None: ...


@dataclass(frozen=True, slots=True)
class RetentionSweepResult:
    dry_run: bool
    eligible_ids: tuple[str, ...]
    deleted_ids: tuple[str, ...]
    protected_ids: tuple[str, ...]


class RetentionSweepHandler:
    """Safety-first RETENTION_SWEEP job. Dry-run is the default."""

    def __init__(self, repository: RetentionRepository, *, dry_run: bool = True) -> None:
        self._repository = repository
        self._dry_run = dry_run

    async def __call__(self, job: QueuedJob) -> RetentionSweepResult:
        candidates = await self._repository.list_candidates(job.aggregate_id)
        eligible: list[RetentionCandidate] = []
        protected: list[str] = []
        safe_cleanup_states = {"ARCHIVED", "DELETE_PENDING", "DELETION_PENDING", "DELETED"}
        for candidate in candidates:
            status = candidate.lifecycle_status.upper()
            if candidate.legal_hold or status not in safe_cleanup_states:
                protected.append(candidate.resource_id)
                continue
            eligible.append(candidate)

        deleted: list[str] = []
        if not self._dry_run:
            for candidate in eligible:
                await self._repository.delete_candidate(candidate)
                deleted.append(candidate.resource_id)

        return RetentionSweepResult(
            dry_run=self._dry_run,
            eligible_ids=tuple(candidate.resource_id for candidate in eligible),
            deleted_ids=tuple(deleted),
            protected_ids=tuple(protected),
        )
