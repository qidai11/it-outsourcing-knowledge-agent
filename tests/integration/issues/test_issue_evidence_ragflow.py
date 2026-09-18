from __future__ import annotations

import asyncio
import os
from datetime import date
from uuid import UUID, uuid4

import httpx
import pytest
from tests.fakes.evidence_governance import FakeEvidenceGovernanceRepository
from tests.fakes.qa_graph_store import InMemoryQAGraphStore

from project_agent.agent.nodes.issue_evidence import retrieve_issue_evidence_node
from project_agent.agent.nodes.serialization import serialize_authorized_context
from project_agent.agent.policies.access import ProjectAccessPolicy
from project_agent.application.ports.knowledge import (
    IngestionState,
    KnowledgeIngestionRequest,
)
from project_agent.application.ports.object_store import ObjectPayload
from project_agent.application.services.authorization import AuthorizedProjectContext
from project_agent.application.services.evidence_governance import (
    DocumentEvidenceMetadata,
    EvidenceGovernanceService,
)
from project_agent.application.services.issue_evidence import IssueEvidenceSelector
from project_agent.domain.access import ProjectAccessScope
from project_agent.domain.enums import (
    AuthorityLevel,
    DocumentCategory,
    DocumentLifecycleStatus,
)
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_RAGFLOW_INTEGRATION") != "1",
    reason="set RUN_RAGFLOW_INTEGRATION=1 to run WS5 real RAGFlow evidence acceptance",
)


class IntegrationObjectStore:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads

    async def get(self, object_key: str) -> ObjectPayload:
        return ObjectPayload(
            object_key=object_key,
            data=self.payloads[object_key],
            mime_type="text/plain",
            sha256="ws5-integration",
        )


async def _create_test_dataset(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    name: str,
) -> str:
    payload: dict[str, str] = {
        "name": name,
        "permission": "me",
        "chunk_method": os.getenv("RAGFLOW_CHUNK_METHOD", "naive"),
    }
    embedding_model = os.getenv("RAGFLOW_EMBEDDING_MODEL", "").strip()
    if embedding_model:
        payload["embedding_model"] = embedding_model

    response = await http.post(
        "/api/v1/datasets",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
    )
    response.raise_for_status()
    envelope = response.json()
    if not isinstance(envelope, dict) or envelope.get("code") != 0:
        pytest.fail(f"RAGFlow dataset creation failed: {envelope!r}")
    data = envelope.get("data")
    if not isinstance(data, dict) or not data.get("id"):
        pytest.fail(f"RAGFlow dataset creation returned no id: {envelope!r}")
    return str(data["id"])


async def _delete_test_datasets(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    dataset_ids: list[str],
) -> None:
    if not dataset_ids:
        return
    response = await http.request(
        "DELETE",
        "/api/v1/datasets",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"ids": dataset_ids},
    )
    response.raise_for_status()
    envelope = response.json()
    if not isinstance(envelope, dict) or envelope.get("code") != 0:
        pytest.fail(f"RAGFlow dataset cleanup failed: {envelope!r}")


async def _wait_for_ingestion(adapter: RagflowAdapter, job_id: str) -> None:
    for _ in range(120):
        status = await adapter.get_ingestion_status(job_id)
        if status.state is IngestionState.SUCCEEDED:
            return
        if status.state is IngestionState.FAILED:
            pytest.fail(f"RAGFlow parsing failed: {status.error_code}")
        await asyncio.sleep(1)
    pytest.fail("RAGFlow parsing did not finish within 120 seconds")


def _metadata(
    *,
    version_id: UUID,
    document_id: UUID,
    project_id: UUID,
    category: DocumentCategory,
    authority: AuthorityLevel,
    title: str,
) -> DocumentEvidenceMetadata:
    return DocumentEvidenceMetadata(
        document_version_id=version_id,
        document_id=document_id,
        project_id=project_id,
        document_category=category,
        title=title,
        authority_level=authority,
        lifecycle_status=DocumentLifecycleStatus.PUBLISHED,
        version_no=1,
        version_label="v1",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        is_current=True,
    )


@pytest.mark.asyncio
async def test_real_ragflow_ws5_freezes_only_authorized_requirement_or_test_evidence() -> None:
    base_url = os.environ["RAGFLOW_BASE_URL"].rstrip("/")
    api_key = os.environ["RAGFLOW_API_KEY"]
    suffix = uuid4().hex[:10]
    token = f"WS5_EVIDENCE_{suffix}"

    project_a_id = uuid4()
    project_b_id = uuid4()
    user_id = uuid4()
    company_id = uuid4()
    client_id = uuid4()
    requirement_version = uuid4()
    design_version = uuid4()
    beta_requirement_version = uuid4()
    project_a_code = "PRJ-RETAIL-ALPHA"
    project_b_code = "PRJ-LOGISTICS-BETA"

    object_store = IntegrationObjectStore(
        {
            "a_requirement": (
                f"{token} requirement: import acceptance failures must create issues."
            ).encode(),
            "a_design": f"{token} design control that WS5 must not freeze.".encode(),
            "b_requirement": (
                f"{token} foreign project requirement that must never cross project scope."
            ).encode(),
        }
    )

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        adapter = RagflowAdapter.from_http_client(
            http,
            api_key=api_key,
            object_store=object_store,
        )
        dataset_ids: list[str] = []
        try:
            alpha_dataset_id = await _create_test_dataset(
                http, api_key=api_key, name=f"ws5-evidence-alpha-{suffix}"
            )
            dataset_ids.append(alpha_dataset_id)
            beta_dataset_id = await _create_test_dataset(
                http, api_key=api_key, name=f"ws5-evidence-beta-{suffix}"
            )
            dataset_ids.append(beta_dataset_id)

            # Live-test bootstrap: use datasets owned by this API key, then bind the
            # provider IDs to the two application project scopes under test.
            adapter._bind_space(project_a_code, alpha_dataset_id)
            adapter._bind_space(project_b_code, beta_dataset_id)

            ingestions = [
                (
                    project_a_code,
                    alpha_dataset_id,
                    str(requirement_version),
                    "a_requirement",
                ),
                (
                    project_a_code,
                    alpha_dataset_id,
                    str(design_version),
                    "a_design",
                ),
                (
                    project_b_code,
                    beta_dataset_id,
                    str(beta_requirement_version),
                    "b_requirement",
                ),
            ]
            receipts = []
            for project_code, space_id, version_id, object_key in ingestions:
                receipt = await adapter.ingest(
                    KnowledgeIngestionRequest(
                        project_code,
                        space_id,
                        version_id,
                        object_key,
                        {"filename": f"{object_key}-{suffix}.txt"},
                    )
                )
                receipts.append((project_code, space_id, version_id, receipt))

            for _project_code, _space_id, _version_id, receipt in receipts:
                await _wait_for_ingestion(adapter, receipt.ingestion_job_id)

            evidence_repo = FakeEvidenceGovernanceRepository()
            evidence_repo.records[requirement_version] = _metadata(
                version_id=requirement_version,
                document_id=uuid4(),
                project_id=project_a_id,
                category=DocumentCategory.REQUIREMENT_BASELINE,
                authority=AuthorityLevel.REQUIREMENT_BASELINE,
                title="WS5 requirement",
            )
            evidence_repo.records[design_version] = _metadata(
                version_id=design_version,
                document_id=uuid4(),
                project_id=project_a_id,
                category=DocumentCategory.APPROVED_DESIGN,
                authority=AuthorityLevel.APPROVED_DESIGN,
                title="WS5 design control",
            )
            evidence_repo.records[beta_requirement_version] = _metadata(
                version_id=beta_requirement_version,
                document_id=uuid4(),
                project_id=project_b_id,
                category=DocumentCategory.REQUIREMENT_BASELINE,
                authority=AuthorityLevel.REQUIREMENT_BASELINE,
                title="Foreign requirement",
            )

            context = AuthorizedProjectContext(
                scope=ProjectAccessScope(
                    company_id=company_id,
                    user_id=user_id,
                    allowed_client_ids=(client_id,),
                    allowed_project_ids=(project_a_id,),
                    allowed_document_version_ids=(requirement_version, design_version),
                    allowed_document_categories=(
                        DocumentCategory.REQUIREMENT_BASELINE.value,
                        DocumentCategory.APPROVED_DESIGN.value,
                    ),
                    role_ids=("developer",),
                    max_security_level=0,
                    policy_version="ws5-live-ragflow",
                ),
                project_code=project_a_code,
                knowledge_space_ids=(alpha_dataset_id,),
            )
            run_id = uuid4()
            store = InMemoryQAGraphStore()
            store.seed_query(run_id, token)
            scope_id = await store.save_artifact(
                run_id=run_id,
                artifact_type="PROJECT_ACCESS_SCOPE",
                payload=serialize_authorized_context(context),
            )

            result = await retrieve_issue_evidence_node(
                {
                    "run_id": str(run_id),
                    "thread_id": str(uuid4()),
                    "user_id": str(user_id),
                    "project_id": str(project_a_id),
                    "access_scope_id": str(scope_id),
                    "route": None,
                    "last_error_code": None,
                },
                selector=IssueEvidenceSelector(evidence_repo),
                knowledge=adapter,
                access_policy=ProjectAccessPolicy(),
                evidence_governance=EvidenceGovernanceService(evidence_repo),
                store=store,
            )

            assert result["route"] == "issue_evidence_ready"
            bundle = await store.load_governed_evidence_bundle(
                UUID(str(result["evidence_bundle_id"]))
            )
            assert bundle.evidence
            assert {item.project_id for item in bundle.evidence} == {project_a_id}
            assert {item.document_version_id for item in bundle.evidence} == {
                requirement_version
            }
            assert {item.document_category for item in bundle.evidence} == {
                DocumentCategory.REQUIREMENT_BASELINE
            }
            assert all(
                item.knowledge_space_id == alpha_dataset_id
                for item in bundle.evidence
            )
            assert design_version not in {item.document_version_id for item in bundle.evidence}
            assert beta_requirement_version not in {
                item.document_version_id for item in bundle.evidence
            }
            assert store.telemetry[run_id].retrieval_rounds == 1
        finally:
            await _delete_test_datasets(
                http,
                api_key=api_key,
                dataset_ids=dataset_ids,
            )
