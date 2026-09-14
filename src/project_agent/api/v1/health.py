from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

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
    """Readiness probe for Task 1: validate local configuration only."""

    try:
        _resolve_settings(request)
    except ValidationError:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "configuration": "invalid"},
        )

    return {"status": "ready", "configuration": "ok"}
