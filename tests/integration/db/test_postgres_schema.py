from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

RUN_POSTGRES_INTEGRATION = os.getenv("RUN_POSTGRES_INTEGRATION") == "1"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_POSTGRES_INTEGRATION,
    reason="set RUN_POSTGRES_INTEGRATION=1 after starting PostgreSQL and applying migrations",
)
async def test_migrated_postgres_contains_gate2_schema() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)

    try:
        async with engine.connect() as connection:
            def inspect_schema(
                sync_connection: object,
            ) -> tuple[set[str], tuple[str, ...] | None, dict[str, bool]]:
                inspector = inspect(sync_connection)
                tables = set(inspector.get_table_names())
                exact_index_columns: tuple[str, ...] | None = None
                for index in inspector.get_indexes("document_identifiers"):
                    if index["name"] == "idx_identifier_exact":
                        exact_index_columns = tuple(index["column_names"])
                        break
                agent_run_columns = {
                    str(column["name"]): bool(column["nullable"])
                    for column in inspector.get_columns("agent_runs")
                }
                return tables, exact_index_columns, agent_run_columns

            tables, exact_index_columns, agent_run_columns = await connection.run_sync(
                inspect_schema
            )
            alembic_version = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )

        assert {
            "clients",
            "projects",
            "project_memberships",
            "project_knowledge_spaces",
            "documents",
            "document_versions",
            "document_acl_bindings",
            "document_identifiers",
            "ingestion_jobs",
            "ingestion_audits",
            "background_jobs",
            "threads",
            "agent_runs",
            "agent_events",
            "evidence_bundles",
            "evidence_snapshots",
            "answers",
            "citations",
            "issue_drafts",
            "issue_candidates",
            "sandbox_projects",
            "sandbox_issues",
            "sandbox_issue_events",
            "tool_confirmations",
            "idempotency_records",
            "audit_logs",
            "system_configs",
            "data_retention_policies",
            "alembic_version",
        } <= tables
        assert exact_index_columns == (
            "project_id",
            "identifier_type",
            "normalized_value",
        )
        assert "business_mode" in agent_run_columns
        assert agent_run_columns["started_at"] is True
        assert alembic_version == "0005_run_runtime_envelope"
    finally:
        await engine.dispose()
