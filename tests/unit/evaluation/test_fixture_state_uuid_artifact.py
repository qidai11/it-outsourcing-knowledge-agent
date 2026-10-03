"""Regression: production fixture state contains deterministic UUID objects."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from project_agent.evaluation.artifacts import ArtifactStore


def test_fixture_state_with_nested_uuid_ids_writes_canonical_json(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "ws8-task2-uuid-regression")
    company = UUID("00000000-0000-5000-8000-000000000001")
    project = UUID("00000000-0000-5000-8000-000000000002")
    version = UUID("00000000-0000-5000-8000-000000000003")
    payload = {
        "evaluation_namespace": "ws8-task2-uuid-regression",
        "company_id": company,
        "project_ids": {"PRJ-RETAIL-ALPHA": project},
        "document_version_ids": {"A-API-001": version},
        "knowledge_space_ids": {"PRJ-RETAIL-ALPHA": "provider-dataset-id"},
        "ragflow_documents": {
            "A-API-001": {"dataset_id": "provider-dataset-id", "document_id": "provider-doc-id"}
        },
    }
    first_hash = store.write_json(store.fixture_state_path, payload)
    stored = json.loads(store.fixture_state_path.read_text(encoding="utf-8"))
    assert stored["company_id"] == str(company)
    assert stored["project_ids"]["PRJ-RETAIL-ALPHA"] == str(project)
    assert stored["document_version_ids"]["A-API-001"] == str(version)
    assert stored["ragflow_documents"] == payload["ragflow_documents"]
    assert first_hash == store.write_json(store.fixture_state_path, payload)
