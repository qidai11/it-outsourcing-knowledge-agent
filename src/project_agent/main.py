from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import ValidationError

from project_agent.api.v1.documents import router as documents_router
from project_agent.api.v1.health import router as health_router
from project_agent.api.v1.runs import router as runs_router
from project_agent.config import Settings, load_settings
from project_agent.runtime.api import ApiRuntimeFactory, build_api_runtime


def create_app(
    settings: Settings | None = None,
    *,
    runtime_factory: ApiRuntimeFactory = build_api_runtime,
) -> FastAPI:
    """Build the FastAPI application without import-time external-service work."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            resolved_settings = settings if settings is not None else load_settings()
        except ValidationError:
            app.state.settings = None
            app.state.runtime = None
            yield
            return

        app.state.settings = resolved_settings
        async with runtime_factory(resolved_settings) as runtime:
            app.state.runtime = runtime
            try:
                yield
            finally:
                app.state.runtime = None

    app = FastAPI(
        title="IT Outsourcing Knowledge and Ticket Collaboration Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.runtime = None
    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(runs_router)
    return app


app = create_app()
