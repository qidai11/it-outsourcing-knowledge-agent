from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_agent.agent.graph import QAGraphDependencies, build_project_qa_graph
from project_agent.agent.nodes.analyze_query import QueryAnalysisService
from project_agent.agent.nodes.resolve_identifiers import ExactIdentifierResolver
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.application.ports.llm import StructuredLLMPort, StructuredLLMUsagePort
from project_agent.application.ports.run_graph import RunGraphExecutor, RunGraphOutcome
from project_agent.application.services.authorization import AuthorizationService
from project_agent.application.services.citation_guard import CitationGuard
from project_agent.application.services.evidence_governance import EvidenceGovernanceService
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.application.services.identifier_registry import IdentifierRegistryService
from project_agent.application.services.prompt_config import PromptConfigService
from project_agent.config import Settings
from project_agent.domain.runs import RunBusinessMode, RunRecord
from project_agent.infrastructure.db.repositories.authorization import (
    SqlAlchemyProjectAuthorizationRepository,
)
from project_agent.infrastructure.db.repositories.evidence_governance import (
    SqlAlchemyEvidenceGovernanceRepository,
)
from project_agent.infrastructure.db.repositories.identifiers import (
    SqlAlchemyIdentifierRegistryRepository,
)
from project_agent.infrastructure.db.repositories.qa_graph import SqlAlchemyQAGraphStore
from project_agent.infrastructure.db.repositories.system_config import (
    SqlAlchemyPromptConfigRepository,
)
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter


class ProductionQARunExecutor(RunGraphExecutor):
    """Build and execute one production QA graph with a fresh application DB session."""

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        saver: object,
        knowledge: RagflowAdapter,
        llm: StructuredLLMPort,
        llm_usage: StructuredLLMUsagePort,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._saver = saver
        self._knowledge = knowledge
        self._llm = llm
        self._llm_usage = llm_usage

    async def execute(self, run: RunRecord) -> RunGraphOutcome:
        if run.business_mode is not RunBusinessMode.QA:
            raise RuntimeError(
                f"production QA executor does not support business mode {run.business_mode.value}"
            )

        async with self._session_factory() as session:
            try:
                deps = self._build_dependencies(session)
                context = await deps.authorization.authorize_project(
                    user_id=run.user_id,
                    project_id=run.project_id,
                )
                for dataset_id in context.knowledge_space_ids:
                    self._knowledge.bind_authorized_space(
                        project_id=context.project_code,
                        dataset_id=dataset_id,
                    )

                compiled = build_project_qa_graph(deps, checkpointer=self._saver)
                delegate = _build_langgraph_executor(compiled)
                outcome = await delegate.execute(run)
                await session.commit()
                return outcome
            except Exception:
                await session.rollback()
                raise

    async def resume(
        self,
        run: RunRecord,
        resume_payload: dict[str, object],
    ) -> RunGraphOutcome:
        del run, resume_payload
        raise RuntimeError("QA runs do not support resume")

    def _build_dependencies(self, session: AsyncSession) -> QAGraphDependencies:
        extractor = IdentifierExtractor()
        authorization = AuthorizationService(SqlAlchemyProjectAuthorizationRepository(session))
        registry = IdentifierRegistryService(
            SqlAlchemyIdentifierRegistryRepository(session),
            extractor,
        )
        return QAGraphDependencies(
            authorization=authorization,
            query_analysis=QueryAnalysisService(extractor),
            exact_resolver=ExactIdentifierResolver(registry),
            knowledge=self._knowledge,
            access_policy=ProjectAccessPolicy(),
            prompt_config=PromptConfigService(
                SqlAlchemyPromptConfigRepository(session),
                ttl_seconds=self._settings.prompt_cache_ttl_seconds,
            ),
            evidence_governance=EvidenceGovernanceService(
                SqlAlchemyEvidenceGovernanceRepository(session)
            ),
            citation_guard=CitationGuard(),
            llm=self._llm,
            llm_usage=self._llm_usage,
            store=SqlAlchemyQAGraphStore(session),
            model_alias=self._settings.llm_model_alias,
        )


def _build_langgraph_executor(compiled_graph: Any) -> RunGraphExecutor:
    # Lazy import keeps non-graph tooling importable in environments where the
    # synchronized LangGraph runtime is intentionally absent.
    from project_agent.workers.run_graph import LangGraphRunExecutor

    return LangGraphRunExecutor({RunBusinessMode.QA: compiled_graph})


def build_production_qa_executor(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    saver: object,
    knowledge: RagflowAdapter,
    llm: StructuredLLMPort,
    llm_usage: StructuredLLMUsagePort,
) -> RunGraphExecutor:
    return ProductionQARunExecutor(
        settings=settings,
        session_factory=session_factory,
        saver=saver,
        knowledge=knowledge,
        llm=llm,
        llm_usage=llm_usage,
    )
