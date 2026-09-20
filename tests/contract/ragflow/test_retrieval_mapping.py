from __future__ import annotations

import json

import httpx
import pytest

from project_agent.application.ports.knowledge import (
    EnsureKnowledgeSpaceRequest,
    KnowledgeRetrievalRequest,
)
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.errors import RagflowProjectIsolationError


@pytest.mark.asyncio
async def test_retrieve_filters_cross_project_and_unmapped_chunks() -> None:
    seen_retrieval_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/datasets":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        {"id": "dataset-alpha", "name": "client-a-project-alpha"},
                        {"id": "dataset-beta", "name": "client-b-project-beta"},
                    ],
                },
            )

        if request.method == "POST" and request.url.path == "/api/v1/retrieval":
            seen_retrieval_payload.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "chunks": [
                            {
                                "id": "chunk-alpha",
                                "dataset_id": "dataset-alpha",
                                "document_id": "doc-alpha",
                                "content": "alpha evidence",
                                "similarity": 0.91,
                            },
                            {
                                "id": "chunk-beta-leak",
                                "dataset_id": "dataset-beta",
                                "document_id": "doc-beta",
                                "content": "beta leaked evidence",
                                "similarity": 0.99,
                            },
                            {
                                "id": "chunk-unmapped",
                                "dataset_id": "dataset-alpha",
                                "document_id": "doc-unmapped",
                                "content": "unmapped evidence",
                                "similarity": 0.95,
                            },
                        ]
                    },
                },
            )

        if (
            request.method == "GET"
            and request.url.path == "/api/v1/datasets/dataset-alpha/documents"
        ):
            document_id = request.url.params.get("id")
            if document_id == "doc-alpha":
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "docs": [
                                {
                                    "id": "doc-alpha",
                                    "meta_fields": {
                                        "project_agent_project_id": "PRJ-RETAIL-ALPHA",
                                        "project_agent_document_version_id": "version-alpha-1",
                                        "section": "3.2",
                                    },
                                }
                            ]
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"docs": [{"id": document_id, "meta_fields": {}}]},
                },
            )

        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = RagflowAdapter.from_http_client(http, api_key="secret")
        await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest("PRJ-RETAIL-ALPHA", "client-a-project-alpha")
        )
        await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest("PRJ-LOGISTICS-BETA", "client-b-project-beta")
        )

        chunks = await adapter.retrieve(
            KnowledgeRetrievalRequest(
                project_id="PRJ-RETAIL-ALPHA",
                query="alpha",
                limit=10,
            )
        )

    assert [chunk.content for chunk in chunks] == ["alpha evidence"]
    assert chunks[0].document_version_id == "version-alpha-1"
    assert chunks[0].project_id == "PRJ-RETAIL-ALPHA"
    assert chunks[0].knowledge_space_id == "dataset-alpha"
    assert chunks[0].provider_ref == "chunk-alpha"
    assert chunks[0].metadata["section"] == "3.2"
    assert seen_retrieval_payload["dataset_ids"] == ["dataset-alpha"]
    metadata_condition = seen_retrieval_payload["metadata_condition"]
    assert metadata_condition == {
        "logic": "and",
        "conditions": [
            {
                "name": "project_agent_project_id",
                "comparison_operator": "=",
                "value": "PRJ-RETAIL-ALPHA",
            }
        ],
    }


@pytest.mark.asyncio
async def test_retrieve_rejects_knowledge_space_bound_to_another_project() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/datasets"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [{"id": "dataset-beta", "name": "client-b-project-beta"}],
            },
        )

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = RagflowAdapter.from_http_client(http, api_key="secret")
        await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest("PRJ-LOGISTICS-BETA", "client-b-project-beta")
        )

        with pytest.raises(RagflowProjectIsolationError):
            await adapter.retrieve(
                KnowledgeRetrievalRequest(
                    project_id="PRJ-RETAIL-ALPHA",
                    query="anything",
                    knowledge_space_ids=("dataset-beta",),
                )
            )


@pytest.mark.asyncio
async def test_authorized_binding_seeds_worker_retrieval_scope_without_auto_binding() -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/retrieval":
            seen_payload.update(json.loads(request.content))
            return httpx.Response(200, json={"code": 0, "data": {"chunks": []}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = RagflowAdapter.from_http_client(http, api_key="secret")
        adapter.bind_authorized_space(
            project_id="PRJ-RETAIL-ALPHA",
            dataset_id="dataset-a",
        )
        await adapter.retrieve(
            KnowledgeRetrievalRequest(
                project_id="PRJ-RETAIL-ALPHA",
                query="alpha",
                knowledge_space_ids=("dataset-a",),
            )
        )
        assert seen_payload["dataset_ids"] == ["dataset-a"]

        with pytest.raises(RagflowProjectIsolationError):
            adapter.bind_authorized_space(
                project_id="PRJ-LOGISTICS-BETA",
                dataset_id="dataset-a",
            )

        with pytest.raises(RagflowProjectIsolationError):
            await adapter.retrieve(
                KnowledgeRetrievalRequest(
                    project_id="PRJ-RETAIL-ALPHA",
                    query="unbound",
                    knowledge_space_ids=("dataset-unbound",),
                )
            )
