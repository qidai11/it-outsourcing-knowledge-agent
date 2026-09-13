from __future__ import annotations

RAGFLOW_STABLE_VERSION = "v0.26.4"
RAGFLOW_DEFAULT_IMAGE = f"infiniflow/ragflow:{RAGFLOW_STABLE_VERSION}"

# project scope -> deterministic RAGFlow dataset name
BASELINE_DATASET_BINDINGS: dict[str, str] = {
    "company-public": "company-public",
    "PRJ-RETAIL-ALPHA": "client-a-project-alpha",
    "PRJ-LOGISTICS-BETA": "client-b-project-beta",
}

PROJECT_METADATA_FIELD = "project_agent_project_id"
DOCUMENT_VERSION_METADATA_FIELD = "project_agent_document_version_id"
