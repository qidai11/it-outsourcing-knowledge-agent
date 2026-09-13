from __future__ import annotations

import json

import httpx
import pytest

from project_agent.application.ports.knowledge import (
    EnsureKnowledgeSpaceRequest,
    IngestionState,
    KnowledgeIngestionRequest,
)
from project_agent.application.ports.object_store import ObjectPayload
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter


class StubObjectStore:
    async def get(self, object_key: str) -> ObjectPayload:
        assert object_key == "objects/source-1"
        return ObjectPayload(
            object_key=object_key,
            data=b"alpha source document",
            mime_type="text/plain",
            sha256="abc",
        )


@pytest.mark.asyncio
async def test_ingest_uploads_metadata_before_parse_and_status_maps_done() -> None:
    calls: list[tuple[str, str]] = []
    update_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/api/v1/datasets":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [{"id": "dataset-alpha", "name": "client-a-project-alpha"}],
                },
            )
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/datasets/dataset-alpha/documents"
        ):
            assert b'filename="alpha.txt"' in request.content
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [{"id": "doc-alpha", "name": "alpha.txt", "run": "UNSTART"}],
                },
            )
        if (
            request.method == "PUT"
            and request.url.path
            == "/api/v1/datasets/dataset-alpha/documents/doc-alpha"
        ):
            update_payload.update(json.loads(request.content))
            return httpx.Response(200, json={"code": 0, "data": {"id": "doc-alpha"}})
        if request.method == "POST" and request.url.path == "/api/v1/datasets/dataset-alpha/chunks":
            assert json.loads(request.content) == {"document_ids": ["doc-alpha"]}
            return httpx.Response(200, json={"code": 0})
        if (
            request.method == "GET"
            and request.url.path == "/api/v1/datasets/dataset-alpha/documents"
        ):
            assert request.url.params["id"] == "doc-alpha"
            return httpx.Response(
                200,
                json={"code": 0, "data": {"docs": [{"id": "doc-alpha", "run": "DONE"}]}},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = RagflowAdapter.from_http_client(
            http,
            api_key="secret",
            object_store=StubObjectStore(),
        )
        space = await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest("PRJ-RETAIL-ALPHA", "client-a-project-alpha")
        )
        receipt = await adapter.ingest(
            KnowledgeIngestionRequest(
                project_id="PRJ-RETAIL-ALPHA",
                knowledge_space_id=space.knowledge_space_id,
                document_version_id="version-alpha-1",
                object_key="objects/source-1",
                metadata={"filename": "alpha.txt", "authority_level": "requirement_baseline"},
            )
        )
        status = await adapter.get_ingestion_status(receipt.ingestion_job_id)

    assert receipt.document_version_id == "version-alpha-1"
    assert status.state is IngestionState.SUCCEEDED
    assert update_payload["meta_fields"] == {
        "project_agent_project_id": "PRJ-RETAIL-ALPHA",
        "project_agent_document_version_id": "version-alpha-1",
        "authority_level": "requirement_baseline",
    }
    assert calls.index(("PUT", "/api/v1/datasets/dataset-alpha/documents/doc-alpha")) < calls.index(
        ("POST", "/api/v1/datasets/dataset-alpha/chunks")
    )
