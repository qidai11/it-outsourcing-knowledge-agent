"""Regression contract for the production autoflush=False fixture session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from project_agent.evaluation.dataset import load_evaluation_dataset

DATASET = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"


class _NoAutoflushSession:
    """Record when pending parent rows are explicitly made visible."""

    def __init__(self) -> None:
        self.pending_client_ids: set[object] = set()
        self.persisted_client_ids: set[object] = set()
        self.pending_project_ids: set[object] = set()
        self.persisted_project_ids: set[object] = set()
        self.pending_versions = 0
        self.persisted_versions = 0
        self.pending_version_ids: set[object] = set()
        self.persisted_version_ids: set[object] = set()
        self.identifier_count = 0
        self.flush_count = 0
        self.prompt_added = False

    async def __aenter__(self) -> _NoAutoflushSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def merge(self, model: Any) -> Any:
        from project_agent.infrastructure.db.models.schema import (
            ClientModel,
            DocumentIdentifierModel,
            DocumentModel,
            DocumentVersionModel,
            ProjectKnowledgeSpaceModel,
            ProjectMembershipModel,
            ProjectModel,
            SandboxProjectModel,
        )

        if isinstance(model, ClientModel):
            self.pending_client_ids.add(model.id)
        if isinstance(model, ProjectModel):
            assert model.client_id in self.persisted_client_ids, (
                "Client must be flushed before Project to satisfy the FK"
            )
            self.pending_project_ids.add(model.id)
        if isinstance(
            model,
            (
                DocumentModel,
                ProjectMembershipModel,
                ProjectKnowledgeSpaceModel,
                SandboxProjectModel,
            ),
        ):
            assert model.project_id in self.persisted_project_ids, (
                "Project must be flushed before its dependent rows"
            )
        if isinstance(model, DocumentVersionModel):
            if model.supersedes_version_id is not None:
                assert model.supersedes_version_id in self.persisted_version_ids, (
                    "superseded DocumentVersion was not flushed before its successor"
                )
            self.pending_versions += 1
            self.pending_version_ids.add(model.id)
        if isinstance(model, DocumentIdentifierModel):
            # The real PostgreSQL FK fails when the first Identifier is INSERTed
            # before its DocumentVersion is flushed in autoflush=False sessions.
            assert self.persisted_versions >= 19, (
                "Identifier merge before DocumentVersion flush: "
                "production autoflush=False cannot satisfy its FK"
            )
            self.identifier_count += 1
        return model

    async def flush(self) -> None:
        self.flush_count += 1
        self.persisted_client_ids.update(self.pending_client_ids)
        self.pending_client_ids.clear()
        self.persisted_project_ids.update(self.pending_project_ids)
        self.pending_project_ids.clear()
        self.persisted_versions += self.pending_versions
        self.persisted_version_ids.update(self.pending_version_ids)
        self.pending_version_ids.clear()
        self.pending_versions = 0

    async def scalar(self, statement: Any) -> Any:
        return None

    def add(self, model: Any) -> None:
        from project_agent.infrastructure.db.models.schema import SystemConfigModel

        if isinstance(model, SystemConfigModel):
            self.prompt_added = True

    async def commit(self) -> None:
        assert self.identifier_count > 0
        assert self.prompt_added


@pytest.mark.asyncio
async def test_prepare_flushes_document_versions_before_identifiers_without_autoflush() -> None:
    from project_agent.evaluation.fixtures import prepare_v0

    session = _NoAutoflushSession()
    result = await prepare_v0(
        dataset=load_evaluation_dataset(DATASET),
        evaluation_namespace="ws8-unit-autoflush-off",
        session_factory=lambda: session,  # type: ignore[arg-type]
        ragflow_adapter=None,
    )
    assert session.persisted_versions == 19
    assert session.identifier_count == 23
    assert session.flush_count >= 1
    assert session.prompt_added
    assert len(result["document_version_ids"]) == 19
