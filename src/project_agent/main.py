from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import ValidationError

from project_agent.api.v1.documents import router as documents_router
from project_agent.api.v1.health import router as health_router
from project_agent.api.v1.runs import router as runs_router
from project_agent.config import Settings, load_settings
from project_agent.observability.logging import (
    bind_log_context,
    clear_log_context,
    configure_structured_logging,
    elapsed_ms,
    get_logger,
)
from project_agent.observability.metrics import ObservabilityMetrics, metrics_context
from project_agent.observability.sanitization import safe_error_fields
from project_agent.runtime.api import ApiRuntimeFactory, build_api_runtime


def create_app(
    settings: Settings | None = None,
    *,
    runtime_factory: ApiRuntimeFactory = build_api_runtime,
    metrics: ObservabilityMetrics | None = None,
) -> FastAPI:
    """Build the FastAPI application without import-time external-service work."""

    api_metrics = metrics or ObservabilityMetrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            resolved_settings = settings if settings is not None else load_settings()
        except ValidationError:
            app.state.settings = None
            app.state.runtime = None
            yield
            return

        configure_structured_logging(log_level=resolved_settings.log_level)
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
    app.state.metrics = api_metrics

    @app.middleware("http")
    async def observe_http_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        clear_log_context()
        bind_log_context(service="api")
        start_ns = time.perf_counter_ns()
        status_code = 500
        try:
            with metrics_context(api_metrics):
                response = await call_next(request)
            status_code = response.status_code
            return response
        except BaseException as exc:
            route = _route_template(request)
            duration_ms = elapsed_ms(start_ns)
            api_metrics.observe_http(
                method=request.method,
                route=route,
                status_code=500,
                duration_seconds=duration_ms / 1000.0,
            )
            get_logger().error(
                "http_request_failed",
                method=request.method,
                route=route,
                status_code=500,
                duration_ms=duration_ms,
                **safe_error_fields(exc),
            )
            raise
        finally:
            if status_code != 500 or "response" in locals():
                route = _route_template(request)
                duration_ms = elapsed_ms(start_ns)
                api_metrics.observe_http(
                    method=request.method,
                    route=route,
                    status_code=status_code,
                    duration_seconds=duration_ms / 1000.0,
                )
                get_logger().info(
                    "http_request_completed",
                    method=request.method,
                    route=route,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    outcome="success" if status_code < 500 else "error",
                )
            clear_log_context()

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(content=api_metrics.render_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(runs_router)
    return app


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


app = create_app()
