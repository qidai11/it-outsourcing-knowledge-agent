from __future__ import annotations

from fastapi import FastAPI

from project_agent.api.v1.documents import (
    DocumentApiServices,
    router as documents_router,
)
from project_agent.api.v1.health import router as health_router
from project_agent.application.use_cases.upload_document import DocumentActor
from project_agent.config import Settings


def create_app(
    settings: Settings | None = None,
    *,
    document_api_services: DocumentApiServices | None = None,
    document_actor: DocumentActor | None = None,
) -> FastAPI:
    """Build the FastAPI application without contacting external services."""

    app = FastAPI(
        title="IT Outsourcing Knowledge and Ticket Collaboration Agent",
        version="0.1.0",
    )
    app.state.settings = settings
    app.state.document_api_services = document_api_services
    app.state.document_actor = document_actor
    app.include_router(health_router)
    app.include_router(documents_router)
    return app


app = create_app()
