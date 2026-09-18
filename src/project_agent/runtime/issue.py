from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.agent.issue_run_graph import (
    IssueCreateRunGraphDependencies,
    IssueLookupRunGraphDependencies,
    build_issue_create_run_graph,
    build_issue_lookup_run_graph,
)
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.application.ports.knowledge import KnowledgeRetrievalPort
from project_agent.application.ports.run_graph import RunGraphExecutor, RunGraphOutcome
from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.evidence_governance import EvidenceGovernanceService
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.application.services.issue_candidates import IssueCandidateService
from project_agent.application.services.issue_confirmation import IssueConfirmationService
from project_agent.application.services.issue_creation import IssueCreationService
from project_agent.application.services.issue_drafts import IssueDraftService
from project_agent.application.services.issue_evidence import IssueEvidenceSelector
from project_agent.config import Settings
from project_agent.domain.runs import RunBusinessMode, RunRecord
from project_agent.infrastructure.db.repositories.authorization import (
    SqlAlchemyProjectAuthorizationRepository,
)
from project_agent.infrastructure.db.repositories.evidence_governance import (
    SqlAlchemyEvidenceGovernanceRepository,
)
from project_agent.infrastructure.db.repositories.issue_workflow import (
    PostgresIdempotencyStore,
    SqlAlchemyIssueWorkflowRepository,
)
from project_agent.infrastructure.db.repositories.qa_graph import SqlAlchemyQAGraphStore
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.jobs.postgres import PostgresJobQueue
from project_agent.infrastructure.object_store.local import LocalFileObjectStoreAdapter
from project_agent.infrastructure.project_tracker.sandbox import SandboxProjectTrackerAdapter
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.client import RagflowRetryPolicy

type IssueGraphExecutorFactory = Callable[[object], RunGraphExecutor]


class ProductionIssueRunGraphExecutor(RunGraphExecutor):
    """WS5 production RunGraphExecutor for issue_lookup and issue_create only.

    Every graph invocation builds DB-backed services inside one business
    transaction. LangGraph checkpoint state remains owned by the shared WS3
    checkpointer passed through the existing graph-executor factory seam.
    """

    def __init__(
        self,
        settings: Settings,
        checkpointer: object,
        *,
        knowledge: KnowledgeRetrievalPort | None = None,
    ) -> None:
        self._settings = settings
        self._checkpointer = checkpointer
        self._engine = create_engine(settings.database_url)
        self._session_factory = create_session_factory(self._engine)
        self._queue = PostgresJobQueue(
            self._session_factory,
            lease_seconds=settings.worker_lease_seconds,
            retry_base_seconds=settings.worker_retry_base_seconds,
            retry_max_seconds=settings.worker_retry_max_seconds,
        )
        self._http: httpx.AsyncClient | None = None
        self._knowledge: KnowledgeRetrievalPort
        if knowledge is None:
            self._http = httpx.AsyncClient(
                base_url=settings.ragflow_base_url,
                timeout=settings.ragflow_request_timeout_seconds,
            )
            object_store = LocalFileObjectStoreAdapter(settings.local_storage_root)
            self._knowledge = RagflowAdapter.from_http_client(
                self._http,
                api_key=settings.ragflow_api_key.get_secret_value(),
                object_store=object_store,
                embedding_model=settings.ragflow_embedding_model,
                chunk_method=settings.ragflow_chunk_method,
                retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
            )
        else:
            self._knowledge = knowledge

    async def execute(self, run: RunRecord) -> RunGraphOutcome:
        return await self._invoke(run, resume_payload=None)

    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome:
        return await self._invoke(run, resume_payload=resume_payload)

    async def _invoke(
        self,
        run: RunRecord,
        *,
        resume_payload: dict[str, object] | None,
    ) -> RunGraphOutcome:
        async with self._session_factory() as session:
            try:
                graph = self._build_graph(run.business_mode, session)
                from project_agent.workers.run_graph import LangGraphRunExecutor

                delegate = LangGraphRunExecutor({run.business_mode: graph})
                if resume_payload is None:
                    outcome = await delegate.execute(run)
                else:
                    outcome = await delegate.resume(run, resume_payload)
                await session.commit()
                return outcome
            except Exception:
                await session.rollback()
                raise

    def _build_graph(self, mode: RunBusinessMode, session: AsyncSession) -> Any:
        auth_repo = SqlAlchemyProjectAuthorizationRepository(session)
        authorization = AuthorizationService(auth_repo)
        tracker = SandboxProjectTrackerAdapter(session)
        candidates = IssueCandidateService(
            tracker=tracker,
            extractor=IdentifierExtractor(),
        )
        store = SqlAlchemyQAGraphStore(session)

        if mode is RunBusinessMode.ISSUE_LOOKUP:
            return build_issue_lookup_run_graph(
                IssueLookupRunGraphDependencies(
                    authorization=authorization,
                    candidates=candidates,
                    store=store,
                ),
                checkpointer=self._checkpointer,
            )

        if mode is RunBusinessMode.ISSUE_CREATE:
            evidence_repo = SqlAlchemyEvidenceGovernanceRepository(session)
            workflow_repo = SqlAlchemyIssueWorkflowRepository(session)
            drafts = IssueDraftService(workflow_repo)
            confirmations = IssueConfirmationService(
                workflow_repo,
                drafts=drafts,
                ttl=timedelta(seconds=self._settings.tool_confirmation_ttl_seconds),
            )
            creation = IssueCreationService(
                workflow_repo=workflow_repo,
                idempotency=PostgresIdempotencyStore(self._session_factory),
                tracker=tracker,
                authorization=authorization,
                job_queue=self._queue,
                drafts=drafts,
            )
            return build_issue_create_run_graph(
                IssueCreateRunGraphDependencies(
                    authorization=authorization,
                    evidence_selector=IssueEvidenceSelector(evidence_repo),
                    knowledge=self._knowledge,
                    access_policy=ProjectAccessPolicy(),
                    evidence_governance=EvidenceGovernanceService(evidence_repo),
                    candidates=candidates,
                    drafts=drafts,
                    confirmations=confirmations,
                    creation=creation,
                    store=store,
                ),
                checkpointer=self._checkpointer,
            )

        from project_agent.workers.run_graph import RunGraphUnavailable

        raise RunGraphUnavailable(mode.value)

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        await self._engine.dispose()


def build_issue_graph_executor_factory(
    settings: Settings,
    *,
    knowledge: KnowledgeRetrievalPort | None = None,
) -> IssueGraphExecutorFactory:
    def factory(checkpointer: object) -> RunGraphExecutor:
        return ProductionIssueRunGraphExecutor(
            settings,
            checkpointer,
            knowledge=knowledge,
        )

    return factory
