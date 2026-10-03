"""B7-frozen setup/fault protocols driven through production Issue services.

This is an evaluation-only driver, not an Issue graph or an alternate Issue
creation implementation. A response-loss wrapper delegates the real Sandbox
tracker write and loses only its response, preserving request-id reconciliation.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_agent.evaluation.models import EvaluationCase

if TYPE_CHECKING:
    from project_agent.application.ports.project_tracker import (
        CreatedIssue,
        CreateIssueRequest,
        ProjectIssue,
        SearchIssuesRequest,
    )
    from project_agent.application.services.issue_creation import IssueCreationService


@dataclass(frozen=True, slots=True)
class FrozenScenarios:
    setups: Mapping[str, Mapping[str, Any]]
    faults: Mapping[str, Mapping[str, Any]]


def load_frozen_scenarios(dataset_root: Path) -> FrozenScenarios:
    payload = json.loads((dataset_root / "fixtures" / "fault-scenarios.json").read_text(
        encoding="utf-8"
    ))
    if payload.get("dataset_version") != "v0":
        raise ValueError("frozen scenario dataset must be v0")
    setups = {item["scenario_id"]: item for item in payload["setup_scenarios"]}
    faults = {item["scenario_id"]: item for item in payload["fault_scenarios"]}
    if len(setups) != len(payload["setup_scenarios"]) or len(faults) != len(
        payload["fault_scenarios"]
    ):
        raise ValueError("duplicate frozen scenario identifier")
    return FrozenScenarios(setups=setups, faults=faults)


def fixed_request_uuid(evaluation_namespace: str, case_id: str, template: str) -> UUID:
    """A fixed request ID within a case/namespace; never share across cases."""
    if template != "eval-v0-{case_id}-alpha-confirmed-create":
        raise ValueError("unknown frozen fixed logical request template")
    logical = template.format(case_id=case_id)
    return uuid5(NAMESPACE_URL, f"ws8/{evaluation_namespace}/{logical}")


class ProjectTrackerLike(Protocol):
    async def create_issue(self, request: CreateIssueRequest) -> CreatedIssue: ...
    async def get_issue_by_request_id(
        self, project_id: str, request_id: str
    ) -> CreatedIssue | None: ...
    async def search_issues(self, request: SearchIssuesRequest) -> list[ProjectIssue]: ...


class ResponseLossProjectTracker:
    """First real sandbox create persists, then raises exactly one transient timeout."""

    def __init__(self, delegate: ProjectTrackerLike) -> None:
        self._delegate = delegate
        self._lost = False

    async def create_issue(self, request: CreateIssueRequest) -> CreatedIssue:
        created = await self._delegate.create_issue(request)
        if not self._lost:
            self._lost = True
            # SandboxProjectTrackerAdapter.create_issue flushes the insert and
            # provider event. The evaluation driver commits this transaction
            # before invoking reconciliation in a fresh session.
            raise TimeoutError("evaluation response lost after sandbox persistence")
        return created

    async def get_issue_by_request_id(
        self, project_id: str, request_id: str
    ) -> CreatedIssue | None:
        return await self._delegate.get_issue_by_request_id(project_id, request_id)

    async def search_issues(self, request: SearchIssuesRequest) -> list[ProjectIssue]:
        return await self._delegate.search_issues(request)


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    request_id: str
    status: str
    issue_key: str | None = None


class PostgresIssueScenarioDriver:
    """One evaluation-owned, payload-bound draft and real IssueCreationService.

    The measurable Run is created by the existing API in the Runner. The setup
    draft is pinned to that Run with B7's fixed request template; Q016's frozen
    catalog text supplies the issue facts, never LLM-generated material.
    """

    def __init__(
        self,
        *,
        dataset_root: Path,
        evaluation_namespace: str,
        fixture_state: Mapping[str, Any],
        session_factory: async_sessionmaker[AsyncSession],
        reconciliation_timeout_seconds: float = 30.0,
    ) -> None:
        self._frozen = load_frozen_scenarios(dataset_root)
        self._namespace = evaluation_namespace
        self._state = fixture_state
        self._sessions = session_factory
        if reconciliation_timeout_seconds <= 0:
            raise ValueError("reconciliation timeout must be positive")
        self._reconcile_timeout = reconciliation_timeout_seconds
        # Frozen Q016, not a synthesized prompt or an LLM-generated draft.
        from project_agent.evaluation.dataset import load_evaluation_dataset

        catalog = load_evaluation_dataset(dataset_root)
        self._draft_text = next(case.question for case in catalog.cases if case.case_id == "Q016")

    def request_id(self, case: EvaluationCase) -> str:
        from project_agent.evaluation.models import RunProtocol

        if case.case_id not in {"Q044", "Q045"}:
            raise ValueError("not a frozen Issue fault-protocol case")

        protocol = RunProtocol(
            "same_request_replay" if case.case_id == "Q044" else "response_loss_reconcile"
        )
        expected_fault = (
            "FAULT_SAME_REQUEST_REPLAY" if protocol is RunProtocol.SAME_REQUEST_REPLAY
            else "FAULT_CREATE_RESPONSE_LOSS"
        )
        fault = self._frozen.faults[expected_fault]
        setup = self._frozen.setups[fault["requires_setup_scenario"]]
        return str(fixed_request_uuid(
            self._namespace, case.case_id,
            setup["preconditions"]["logical_request_id_template"],
        ))

    async def _prepare_confirmation(self, case: EvaluationCase, run_id: UUID) -> UUID:
        project_id = UUID(str(self._state["project_ids"][case.project_code]))
        actor_id = UUID(str(self._state["user_ids"][case.user_alias]))
        draft_id = UUID(self.request_id(case))
        from project_agent.domain.issues import IssueDraftStatus
        from project_agent.infrastructure.db.models.schema import IssueDraftModel

        async with self._sessions() as session:
            existing = await session.scalar(
                select(IssueDraftModel).where(IssueDraftModel.id == draft_id)
            )
            if existing is not None:
                raise ValueError(
                    "fixed evaluation request_id is already used; choose a new namespace"
                )
            session.add(IssueDraftModel(
                id=draft_id, run_id=run_id, project_id=project_id, created_by=actor_id,
                title=self._draft_text[:512], description=self._draft_text,
                issue_type="bug", proposed_priority="medium", status=IssueDraftStatus.DRAFT.value,
                evidence_ids_json=[], reproduction_steps_json=[],
            ))
            await session.commit()
        from project_agent.application.services.issue_confirmation import IssueConfirmationService
        from project_agent.application.services.issue_drafts import IssueDraftService
        from project_agent.domain.issues import ConfirmationAction
        from project_agent.infrastructure.db.repositories.issue_workflow import (
            SqlAlchemyIssueWorkflowRepository,
        )

        async with self._sessions() as session:
            repo = SqlAlchemyIssueWorkflowRepository(session)
            drafts = IssueDraftService(repo)
            confirmations = IssueConfirmationService(repo, drafts=drafts)
            prepared = await confirmations.prepare(draft_id)
            receipt = await confirmations.record_decision(
                draft_id=draft_id, actor_id=actor_id,
                action=ConfirmationAction.CONFIRM,
                request_payload_hash=prepared.request_payload_hash,
            )
            await session.commit()
            return receipt.id

    async def _service(
        self, session: AsyncSession, *, response_loss: bool
    ) -> IssueCreationService:
        from project_agent.application.ports.job_queue import JobQueuePort
        from project_agent.application.services.authorization import AuthorizationService
        from project_agent.application.services.issue_creation import IssueCreationService
        from project_agent.infrastructure.db.repositories.authorization import (
            SqlAlchemyProjectAuthorizationRepository,
        )
        from project_agent.infrastructure.db.repositories.issue_workflow import (
            PostgresIdempotencyStore,
            SqlAlchemyIssueWorkflowRepository,
        )
        from project_agent.infrastructure.jobs.postgres import SqlAlchemySessionJobEnqueuer
        from project_agent.infrastructure.project_tracker.sandbox import (
            SandboxProjectTrackerAdapter,
        )

        repo = SqlAlchemyIssueWorkflowRepository(session)
        tracker: ProjectTrackerLike = SandboxProjectTrackerAdapter(session)
        if response_loss:
            tracker = ResponseLossProjectTracker(tracker)
        return IssueCreationService(
            workflow_repo=repo,
            idempotency=PostgresIdempotencyStore(self._sessions),
            tracker=tracker,
            authorization=AuthorizationService(SqlAlchemyProjectAuthorizationRepository(session)),
            # IssueCreationService currently types this dependency as the full
            # JobQueuePort even though this path only calls enqueue(). Keep the
            # frozen service unchanged and use the transaction-scoped enqueuer.
            job_queue=cast(JobQueuePort, SqlAlchemySessionJobEnqueuer(session)),
        )

    async def execute(self, case: EvaluationCase, run_id: UUID) -> ScenarioOutcome:
        if case.case_id not in {"Q044", "Q045"}:
            raise ValueError("not a frozen Issue fault-protocol case")
        from project_agent.application.services.issue_creation import IssueCreationStatus

        confirmation_id = await self._prepare_confirmation(case, run_id)
        draft_id = UUID(self.request_id(case))
        actor_id = UUID(str(self._state["user_ids"][case.user_alias]))
        response_loss = case.case_id == "Q045"
        async with self._sessions() as session:
            service = await self._service(session, response_loss=response_loss)
            first = await service.execute(
                draft_id=draft_id, confirmation_id=confirmation_id, actor_id=actor_id,
            )
            await session.commit()  # persist the injected post-create response loss
        if response_loss:
            if first.status is not IssueCreationStatus.PENDING_RECONCILIATION:
                raise ValueError("injected loss did not reach pending reconciliation")
            # A dedicated, bounded reconciliation request using the SAME request ID.
            async with asyncio.timeout(self._reconcile_timeout):
                async with self._sessions() as session:
                    service = await self._service(session, response_loss=False)
                    second = await service.reconcile(draft_id)
                    await session.commit()
        else:
            async with self._sessions() as session:
                service = await self._service(session, response_loss=False)
                second = await service.execute(
                    draft_id=draft_id, confirmation_id=confirmation_id, actor_id=actor_id,
                )
                await session.commit()
        return ScenarioOutcome(
            request_id=str(draft_id), status=second.status.value, issue_key=second.issue_key,
        )
