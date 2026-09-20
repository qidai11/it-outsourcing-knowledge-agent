from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import httpx
import pytest

from project_agent.application.ports.knowledge import (
    DeleteKnowledgeDocumentRequest,
    EnsureKnowledgeSpaceRequest,
    IngestionState,
    KnowledgeIngestionRequest,
    KnowledgeRetrievalRequest,
)
from project_agent.application.ports.object_store import ObjectPayload
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.client import RagflowHttpClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_RAGFLOW_INTEGRATION") != "1",
    reason="set RUN_RAGFLOW_INTEGRATION=1 to run against a real RAGFlow",
)


class IntegrationObjectStore:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads

    async def get(self, object_key: str) -> ObjectPayload:
        data = self.payloads[object_key]
        return ObjectPayload(
            object_key=object_key,
            data=data,
            mime_type="text/plain",
            sha256="integration",
        )


async def _wait_for_ingestion(adapter: RagflowAdapter, job_id: str) -> None:
    for _ in range(120):
        status = await adapter.get_ingestion_status(job_id)
        if status.state is IngestionState.SUCCEEDED:
            return
        if status.state is IngestionState.FAILED:
            pytest.fail(f"RAGFlow parsing failed: {status.error_code}")
        await asyncio.sleep(1)
    pytest.fail("RAGFlow parsing did not finish within 120 seconds")


@pytest.mark.asyncio
async def test_real_ragflow_alpha_query_does_not_return_beta() -> None:
    base_url = os.environ["RAGFLOW_BASE_URL"].rstrip("/")
    api_key = os.environ["RAGFLOW_API_KEY"]
    suffix = uuid4().hex[:10]
    alpha_project = f"WS4-ISO-ALPHA-{suffix}"
    beta_project = f"WS4-ISO-BETA-{suffix}"
    alpha_space_key = f"ws4-isolation-alpha-{suffix}"
    beta_space_key = f"ws4-isolation-beta-{suffix}"
    alpha_token = f"ALPHA_ONLY_{suffix}"
    beta_token = f"BETA_ONLY_{suffix}"
    store = IntegrationObjectStore(
        {
            "alpha": f"{alpha_token} means retail alpha acceptance evidence.".encode(),
            "beta": f"{beta_token} means logistics beta settlement evidence.".encode(),
        }
    )

    created_space_ids: list[str] = []
    embedding_model = os.getenv("RAGFLOW_EMBEDDING_MODEL") or None

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        adapter = RagflowAdapter.from_http_client(
            http,
            api_key=api_key,
            object_store=store,
            embedding_model=embedding_model,
        )
        alpha_space = await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest(alpha_project, alpha_space_key)
        )
        created_space_ids.append(alpha_space.knowledge_space_id)
        beta_space = await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest(beta_project, beta_space_key)
        )
        created_space_ids.append(beta_space.knowledge_space_id)

        alpha_version = f"integration-alpha-{suffix}"
        beta_version = f"integration-beta-{suffix}"
        alpha_receipt = await adapter.ingest(
            KnowledgeIngestionRequest(
                alpha_project,
                alpha_space.knowledge_space_id,
                alpha_version,
                "alpha",
                {"filename": f"alpha-{suffix}.txt"},
            )
        )
        beta_receipt = await adapter.ingest(
            KnowledgeIngestionRequest(
                beta_project,
                beta_space.knowledge_space_id,
                beta_version,
                "beta",
                {"filename": f"beta-{suffix}.txt"},
            )
        )

        try:
            await _wait_for_ingestion(adapter, alpha_receipt.ingestion_job_id)
            await _wait_for_ingestion(adapter, beta_receipt.ingestion_job_id)

            chunks = await adapter.retrieve(
                KnowledgeRetrievalRequest(
                    project_id=alpha_project,
                    query=alpha_token,
                    limit=10,
                )
            )
            assert chunks
            assert all(chunk.project_id == alpha_project for chunk in chunks)
            assert all(
                chunk.knowledge_space_id == alpha_space.knowledge_space_id
                for chunk in chunks
            )
            assert all(beta_token not in chunk.content for chunk in chunks)
            assert all(chunk.document_version_id != beta_version for chunk in chunks)
        finally:
            await adapter.delete_document(
                DeleteKnowledgeDocumentRequest(
                    alpha_project, alpha_version, alpha_space.knowledge_space_id
                )
            )
            await adapter.delete_document(
                DeleteKnowledgeDocumentRequest(
                    beta_project, beta_version, beta_space.knowledge_space_id
                )
            )
            cleanup_client = RagflowHttpClient(http, api_key=api_key)
            await cleanup_client.request_data(
                "DELETE",
                "/api/v1/datasets",
                json={"ids": created_space_ids},
            )
