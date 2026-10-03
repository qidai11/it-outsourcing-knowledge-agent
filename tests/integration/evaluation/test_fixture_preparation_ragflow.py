"""WS8 Task 2 live RAGFlow RED; requires isolated PostgreSQL + RAGFlow.

All provider datasets created here are evaluation-owned and carry the unique
WS8/V0 namespace.  Never delete a provider dataset by an unscoped name.
The fixture's cleanup delegates ownership validation to Task 2 cleanup_v0.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from project_agent.application.ports.object_store import ObjectPayload
from project_agent.evaluation.dataset import EvaluationDataset, load_evaluation_dataset

DATASET_ROOT = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "v0"

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_RAGFLOW_INTEGRATION") != "1"
    or os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="set both integration flags; requires WS8_EVAL_DATABASE_URL and RAGFlow credentials",
)


class FrozenCorpusObjectStore:
    """Read frozen bytes without changing corpus hashes or production storage."""

    def __init__(self, dataset: EvaluationDataset) -> None:
        self.dataset = dataset
        self.path_by_key = {
            key: doc.source_path
            for code, doc in dataset.documents_by_code.items()
            for key in (code, doc.source_path)
        }

    async def get(self, object_key: str) -> ObjectPayload:
        relative_path = self.path_by_key[object_key]
        full_path = (self.dataset.root / relative_path).resolve()
        assert full_path.is_relative_to(self.dataset.root)
        payload = full_path.read_bytes()
        return ObjectPayload(
            object_key=object_key,
            data=payload,
            mime_type="text/markdown",
            sha256=hashlib.sha256(payload).hexdigest(),
        )


def _eval_db_url() -> str:
    url = os.environ["WS8_EVAL_DATABASE_URL"]
    db_name = url.rsplit("/", maxsplit=1)[-1].split("?", maxsplit=1)[0]
    if "eval" not in db_name.lower() or url == os.getenv("DATABASE_URL"):
        pytest.fail("RAGFlow live tests require a non-primary, dedicated eval PostgreSQL DB")
    return url


async def _provider_documents(client: Any, dataset_id: str) -> dict[str, dict[str, Any]]:
    """List provider document IDs, including any frozen stale test residue."""
    documents: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        data = await client.request_data(
            "GET", f"/api/v1/datasets/{dataset_id}/documents",
            params={"page": page, "page_size": 100},
        )
        records = data.get("docs", []) if isinstance(data, dict) else data
        assert isinstance(records, list)
        for item in records:
            documents[str(item["id"])] = item
        if len(records) < 100:
            return documents
        page += 1


@pytest.fixture
async def prepared_ragflow() -> Any:
    from project_agent.evaluation.fixtures import cleanup_v0, prepare_v0
    from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
    from project_agent.infrastructure.ragflow.client import RagflowHttpClient

    database_url = _eval_db_url()
    api_key = os.environ["RAGFLOW_API_KEY"]
    base_url = os.environ["RAGFLOW_BASE_URL"].rstrip("/")
    namespace = f"ws8-v0-ragflow-red-{uuid4().hex}"
    dataset = load_evaluation_dataset(DATASET_ROOT)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        provider = RagflowHttpClient(http, api_key=api_key)
        adapter = RagflowAdapter.from_http_client(
            http,
            api_key=api_key,
            object_store=FrozenCorpusObjectStore(dataset),
            embedding_model=os.getenv("RAGFLOW_EMBEDDING_MODEL") or None,
        )
        try:
            state = await prepare_v0(
                dataset=dataset,
                evaluation_namespace=namespace,
                session_factory=sessions,
                ragflow_adapter=adapter,
            )
            yield dataset, namespace, sessions, state, adapter, provider
        finally:
            try:
                await cleanup_v0(
                    evaluation_namespace=namespace,
                    session_factory=sessions,
                    ragflow_adapter=adapter,
                )
            finally:
                await engine.dispose()


@pytest.mark.asyncio
async def test_prepare_v0_creates_dedicated_eval_datasets(prepared_ragflow: Any) -> None:
    _dataset, namespace, _sessions, state, _adapter, provider = prepared_ragflow
    spaces = state["knowledge_space_ids"]
    required_projects = {"PRJ-RETAIL-ALPHA", "PRJ-LOGISTICS-BETA"}
    assert required_projects.issubset(spaces)
    assert set(spaces) - required_projects <= {"company-public"}  # Optional non-Run corpus.
    assert spaces["PRJ-RETAIL-ALPHA"] != spaces["PRJ-LOGISTICS-BETA"]

    datasets: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        data = await provider.request_data(
            "GET", "/api/v1/datasets", params={"page": page, "page_size": 100}
        )
        assert isinstance(data, list)
        datasets.update({str(item["id"]): item for item in data})
        if len(data) < 100:
            break
        page += 1
    for provider_dataset_id in spaces.values():
        assert str(provider_dataset_id) in datasets
        dataset_name = str(datasets[str(provider_dataset_id)]["name"]).lower()
        assert "ws8" in dataset_name and "v0" in dataset_name
        assert namespace.lower() in dataset_name


@pytest.mark.asyncio
async def test_prepare_v0_ingests_normal_published_corpus(prepared_ragflow: Any) -> None:
    from project_agent.infrastructure.ragflow.baseline import (
        DOCUMENT_VERSION_METADATA_FIELD,
        PROJECT_METADATA_FIELD,
    )

    dataset, _namespace, _sessions, state, _adapter, provider = prepared_ragflow
    provider_docs = state["ragflow_documents"]  # doc_code -> {dataset_id, document_id}
    for code, frozen in dataset.documents_by_code.items():
        if frozen.project_code not in state["project_ids"]:
            continue  # company-public is not a supported Run scope (Q046).
        if frozen.lifecycle_status != "PUBLISHED":
            continue
        mapping = provider_docs[code]
        expected_dataset_id = str(state["knowledge_space_ids"][frozen.project_code])
        assert str(mapping["dataset_id"]) == expected_dataset_id
        documents = await _provider_documents(provider, expected_dataset_id)
        actual = documents[str(mapping["document_id"])]
        metadata = actual["meta_fields"]
        assert metadata[PROJECT_METADATA_FIELD] == frozen.project_code
        assert metadata[DOCUMENT_VERSION_METADATA_FIELD] == str(
            state["document_version_ids"][code]
        )
        assert actual.get("run") in ("DONE", "COMPLETED", "done", "completed")


@pytest.mark.asyncio
async def test_prepare_v0_materializes_adversarial_provider_residue_only_when_frozen(
    prepared_ragflow: Any,
) -> None:
    dataset, _namespace, _sessions, state, _adapter, provider = prepared_ragflow
    provider_docs = state["ragflow_documents"]
    expected_codes = {
        code for code, frozen in dataset.documents_by_code.items()
        if frozen.project_code in state["project_ids"]
        and (frozen.lifecycle_status == "PUBLISHED"
             or frozen.provider_residue_mode == "adversarial_test_only")
    }
    project_provider_docs = {
        code: mapping for code, mapping in provider_docs.items()
        if dataset.documents_by_code[code].project_code in state["project_ids"]
    }
    assert set(project_provider_docs) == expected_codes
    # A separate company-public evaluation dataset is optional, never a fake Run project.
    assert set(provider_docs) - expected_codes <= {
        code for code, doc in dataset.documents_by_code.items()
        if doc.project_code == "company-public" and doc.lifecycle_status == "PUBLISHED"
    }
    for project_code in state["project_ids"]:
        provider_dataset_id = state["knowledge_space_ids"][project_code]
        actual = await _provider_documents(provider, str(provider_dataset_id))
        expected_provider_ids = {
            str(provider_docs[code]["document_id"])
            for code in expected_codes
            if dataset.documents_by_code[code].project_code == project_code
        }
        assert set(actual) == expected_provider_ids
    stale_codes = {
        code for code in expected_codes
        if dataset.documents_by_code[code].lifecycle_status != "PUBLISHED"
    }
    assert stale_codes == {
        "A-DEL-001", "A-DRAFT-001", "A-REQ-001-OLD",
        "B-DRAFT-001", "B-REQ-001-OLD",
    }


@pytest.mark.asyncio
async def test_prepare_v0_never_binds_alpha_dataset_to_beta_project(prepared_ragflow: Any) -> None:
    from project_agent.infrastructure.ragflow.baseline import PROJECT_METADATA_FIELD

    dataset, _namespace, _sessions, state, adapter, provider = prepared_ragflow
    alpha_project_id = str(state["project_ids"]["PRJ-RETAIL-ALPHA"])
    beta_project_id = str(state["project_ids"]["PRJ-LOGISTICS-BETA"])
    alpha_scope = "PRJ-RETAIL-ALPHA"
    beta_scope = "PRJ-LOGISTICS-BETA"
    alpha_space = str(state["knowledge_space_ids"][alpha_scope])
    beta_space = str(state["knowledge_space_ids"][beta_scope])

    assert alpha_project_id != beta_project_id
    assert alpha_space != beta_space

    assert (
        adapter.space_ids_for_project(alpha_scope)
        == (alpha_space,)
    )
    assert (
        adapter.space_ids_for_project(beta_scope)
        == (beta_space,)
    )

    assert adapter.space_ids_for_project(
        alpha_project_id
    ) == ()

    assert adapter.space_ids_for_project(
        beta_project_id
    ) == ()
    alpha_documents = await _provider_documents(provider, alpha_space)
    beta_documents = await _provider_documents(provider, beta_space)
    for code, mapping in state["ragflow_documents"].items():
        if dataset.documents_by_code[code].project_code == "company-public":
            continue  # Optional provider-only corpus must not join a project dataset.
        expected_space = (
            alpha_space if dataset.documents_by_code[code].project_code == "PRJ-RETAIL-ALPHA"
            else beta_space
        )
        assert str(mapping["dataset_id"]) == expected_space
        actual = (alpha_documents if expected_space == alpha_space else beta_documents)[
            str(mapping["document_id"])
        ]
        expected_project = dataset.documents_by_code[code].project_code
        assert actual["meta_fields"][PROJECT_METADATA_FIELD] == expected_project


@pytest.mark.asyncio
async def test_prepare_v0_reuses_existing_matching_eval_dataset_idempotently(
    prepared_ragflow: Any,
) -> None:
    from project_agent.evaluation.fixtures import prepare_v0

    dataset, namespace, sessions, first_state, adapter, provider = prepared_ragflow
    before = {
        project_code: await _provider_documents(provider, str(space_id))
        for project_code, space_id in first_state["knowledge_space_ids"].items()
    }
    second_state = await prepare_v0(
        dataset=dataset,
        evaluation_namespace=namespace,
        session_factory=sessions,
        ragflow_adapter=adapter,
    )
    assert second_state["knowledge_space_ids"] == first_state["knowledge_space_ids"]
    assert second_state["ragflow_documents"] == first_state["ragflow_documents"]
    after = {
        project_code: await _provider_documents(provider, str(space_id))
        for project_code, space_id in second_state["knowledge_space_ids"].items()
    }
    assert {key: set(value) for key, value in before.items()} == {
        key: set(value) for key, value in after.items()
    }
