from __future__ import annotations

from dataclasses import fields, is_dataclass

from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.application.ports.project_tracker import ProjectIssue


def test_external_ports_expose_canonical_fields_not_provider_raw_fields() -> None:
    assert is_dataclass(KnowledgeChunk)
    knowledge_fields = {field.name for field in fields(KnowledgeChunk)}
    assert "dataset_id" not in knowledge_fields
    assert "chunk_id" not in knowledge_fields
    assert {"project_id", "document_version_id", "content", "score"} <= knowledge_fields

    assert is_dataclass(ProjectIssue)
    issue_fields = {field.name for field in fields(ProjectIssue)}
    assert "sandbox_issue_id" not in issue_fields
    assert "db_row" not in issue_fields
    assert {"project_id", "issue_key", "title", "status"} <= issue_fields
