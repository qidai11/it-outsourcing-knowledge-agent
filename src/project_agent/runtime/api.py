from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol, TypeAlias

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from project_agent.application.ports.knowledge import KnowledgeAdminPort, KnowledgeIngestionPort
from project_agent.application.ports.object_store import ObjectStorePort
from project_agent.config import Settings
from project_agent.infrastructure.auth.jwt import JwtIdentityVerifier
from project_agent.infrastructure.db.session import create_engine, create_session_factory
from project_agent.infrastructure.object_store.local import LocalFileObjectStoreAdapter
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.client import RagflowRetryPolicy


class DocumentKnowledgePort(KnowledgeIngestionPort, KnowledgeAdminPort, Protocol):
    """Combined Task 6 knowledge boundary used by publish/delete routes."""


@dataclass(slots=True)
class ApiRuntime:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    object_store: ObjectStorePort
    knowledge: DocumentKnowledgePort
    jwt_verifier: JwtIdentityVerifier


ApiRuntimeFactory: TypeAlias = Callable[[Settings], AbstractAsyncContextManager[ApiRuntime]]


@asynccontextmanager
async def build_api_runtime(settings: Settings) -> AsyncIterator[ApiRuntime]:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    object_store = LocalFileObjectStoreAdapter(settings.local_storage_root)
    jwt_verifier = JwtIdentityVerifier(
        secret=settings.jwt_hs256_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        leeway_seconds=settings.jwt_leeway_seconds,
    )

    async with httpx.AsyncClient(
        base_url=settings.ragflow_base_url,
        timeout=settings.ragflow_request_timeout_seconds,
    ) as ragflow_http:
        knowledge = RagflowAdapter.from_http_client(
            ragflow_http,
            api_key=settings.ragflow_api_key.get_secret_value(),
            object_store=object_store,
            embedding_model=settings.ragflow_embedding_model,
            chunk_method=settings.ragflow_chunk_method,
            retry_policy=RagflowRetryPolicy(max_attempts=settings.ragflow_max_attempts),
        )
        try:
            yield ApiRuntime(
                settings=settings,
                engine=engine,
                session_factory=session_factory,
                object_store=object_store,
                knowledge=knowledge,
                jwt_verifier=jwt_verifier,
            )
        finally:
            await engine.dispose()
