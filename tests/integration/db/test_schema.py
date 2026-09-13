from __future__ import annotations

from sqlalchemy import Index, UniqueConstraint

import project_agent.infrastructure.db.models  # noqa: F401
from project_agent.infrastructure.db.base import Base


REQUIRED_TABLES = {
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
}


def _unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_required_tables_exist() -> None:
    assert REQUIRED_TABLES <= set(Base.metadata.tables)


def test_required_unique_constraints_exist() -> None:
    assert ("company_id", "code") in _unique_column_sets("projects")
    assert ("document_id", "version_no") in _unique_column_sets("document_versions")
    assert (
        "project_id",
        "identifier_type",
        "normalized_value",
        "document_version_id",
    ) in _unique_column_sets("document_identifiers")
    assert ("run_id", "sequence_no") in _unique_column_sets("agent_events")
    assert ("namespace", "request_id") in _unique_column_sets("idempotency_records")
    assert ("project_id", "issue_key") in _unique_column_sets("sandbox_issues")


def test_identifier_exact_index_has_expected_columns() -> None:
    table = Base.metadata.tables["document_identifiers"]
    indexes = {index.name: index for index in table.indexes if isinstance(index, Index)}

    index = indexes["idx_identifier_exact"]
    assert tuple(column.name for column in index.columns) == (
        "project_id",
        "identifier_type",
        "normalized_value",
    )


def test_agent_runs_contains_prompt_usage_and_cost_fields() -> None:
    columns = set(Base.metadata.tables["agent_runs"].columns.keys())
    expected = {
        "model_alias",
        "prompt_version",
        "prompt_content_hash",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "retrieval_rounds",
        "ocr_pages",
        "estimated_cost_microunits",
        "cost_currency",
    }
    assert expected <= columns


def test_governance_tables_exist_with_required_fields() -> None:
    system_config_columns = set(Base.metadata.tables["system_configs"].columns.keys())
    retention_columns = set(Base.metadata.tables["data_retention_policies"].columns.keys())

    assert {
        "config_key",
        "config_value_json",
        "version",
        "content_hash",
        "enabled",
        "updated_by",
        "updated_at",
    } <= system_config_columns

    assert {
        "scope_type",
        "scope_id",
        "resource_type",
        "retain_days",
        "archive_before_delete",
        "legal_hold",
        "enabled",
        "policy_version",
    } <= retention_columns
