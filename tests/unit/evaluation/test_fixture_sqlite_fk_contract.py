"""Real SQLAlchemy FK check without live services or production database access."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from project_agent.evaluation.dataset import load_evaluation_dataset
from project_agent.infrastructure.db.base import Base
from project_agent.infrastructure.db.models.schema import (
    ClientModel,
    DocumentIdentifierModel,
    DocumentModel,
    DocumentVersionModel,
    ProjectKnowledgeSpaceModel,
    ProjectMembershipModel,
    ProjectModel,
    SandboxIssueModel,
    SandboxProjectModel,
    SystemConfigModel,
)

DATASET = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"


class _SyncSqliteAsyncPort:
    """Async interface backed by a real SQLAlchemy Session(autoflush=False)."""

    def __init__(self, engine: Any) -> None:
        self._inner = Session(bind=engine, expire_on_commit=False, autoflush=False)

    async def __aenter__(self) -> _SyncSqliteAsyncPort:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None:
            self._inner.rollback()
        self._inner.close()

    async def merge(self, model: Any) -> Any:
        return self._inner.merge(model)

    async def flush(self) -> None:
        self._inner.flush()

    def add(self, model: Any) -> None:
        self._inner.add(model)

    async def scalar(self, statement: Any) -> Any:
        return self._inner.scalar(statement)

    async def commit(self) -> None:
        self._inner.commit()


@pytest.mark.asyncio
async def test_real_sqlalchemy_autoflush_false_keeps_all_fixture_foreign_keys() -> None:
    """Exercise real SQL INSERT order, not only a mock flush-call contract."""
    from project_agent.evaluation.fixtures import prepare_v0

    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: Any, _: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    classes = (
        ClientModel, ProjectModel, ProjectMembershipModel, ProjectKnowledgeSpaceModel,
        SandboxProjectModel, SandboxIssueModel, DocumentModel, DocumentVersionModel,
        DocumentIdentifierModel, SystemConfigModel,
    )
    try:
        Base.metadata.create_all(engine, tables=[model.__table__ for model in classes])
        dataset = load_evaluation_dataset(DATASET)
        await prepare_v0(
            dataset=dataset,
            evaluation_namespace="ws8-sqlite-fk-contract",
            session_factory=lambda: _SyncSqliteAsyncPort(engine),  # type: ignore[arg-type]
            ragflow_adapter=None,
        )
        # A repeated prepare must reuse the enabled prompt instead of inserting
        # another global config version.
        await prepare_v0(
            dataset=dataset,
            evaluation_namespace="ws8-sqlite-fk-contract",
            session_factory=lambda: _SyncSqliteAsyncPort(engine),  # type: ignore[arg-type]
            ragflow_adapter=None,
        )
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(DocumentVersionModel)) == 19
            assert session.scalar(select(func.count()).select_from(DocumentIdentifierModel)) == 23
            prompts = list(
                session.scalars(
                    select(SystemConfigModel).where(
                        SystemConfigModel.config_key == "prompt.qa.answer",
                        SystemConfigModel.enabled.is_(True),
                    )
                ).all()
            )
            assert len(prompts) == 1
            prompt = prompts[0]
            expected = (
                "Answer only from governed project evidence. Every factual claim must cite "
                "the supplied Evidence IDs."
            )
            assert prompt.config_value_json == {"content": expected}
            assert prompt.content_hash == sha256(expected.encode()).hexdigest()
            assert session.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    finally:
        engine.dispose()
