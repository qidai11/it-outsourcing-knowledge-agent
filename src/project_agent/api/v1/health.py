from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text

from project_agent.config import Settings, load_settings

router = APIRouter(tags=["health"])


def _resolve_settings(request: Request) -> Settings:
    injected_settings = getattr(request.app.state, "settings", None)
    if isinstance(injected_settings, Settings):
        return injected_settings
    return load_settings()


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness probe: process is running; no external dependency checks."""

    return {"status": "ok"}


@router.get("/ready", response_model=None)
async def ready(request: Request) -> dict[str, str] | JSONResponse:
    """Readiness probe: valid configuration plus reachable PostgreSQL."""

    try:
        _resolve_settings(request)
    except ValidationError:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "configuration": "invalid"},
        )

    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "configuration": "ok",
                "database": "unavailable",
            },
        )

    try:
        async with runtime.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "configuration": "ok",
                "database": "unavailable",
            },
        )

    return {"status": "ready", "configuration": "ok", "database": "ok"}
