from __future__ import annotations

import httpx
import pytest

from project_agent.application.ports.knowledge import EnsureKnowledgeSpaceRequest
from project_agent.infrastructure.ragflow.adapter import RagflowAdapter
from project_agent.infrastructure.ragflow.errors import RagflowProjectIsolationError


@pytest.mark.asyncio
async def test_ensure_space_reuses_existing_dataset_and_binds_project() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/v1/datasets"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [
                    {
                        "id": "dataset-alpha",
                        "name": "client-a-project-alpha",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = RagflowAdapter.from_http_client(http, api_key="secret")
        space = await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest(
                project_id="PRJ-RETAIL-ALPHA",
                space_key="client-a-project-alpha",
            )
        )

        assert space.knowledge_space_id == "dataset-alpha"
        assert adapter.space_ids_for_project("PRJ-RETAIL-ALPHA") == ("dataset-alpha",)

        with pytest.raises(RagflowProjectIsolationError):
            await adapter.ensure_space(
                EnsureKnowledgeSpaceRequest(
                    project_id="PRJ-LOGISTICS-BETA",
                    space_key="client-a-project-alpha",
                )
            )

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_ensure_space_creates_missing_dataset() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"code": 0, "data": []})
        assert request.method == "POST"
        payload = __import__("json").loads(request.content)
        assert payload["name"] == "company-public"
        assert payload["permission"] == "me"
        assert payload["chunk_method"] == "naive"
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": "dataset-public", "name": "company-public"}},
        )

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = RagflowAdapter.from_http_client(http, api_key="secret")
        space = await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest(project_id="company-public", space_key="company-public")
        )

    assert space.knowledge_space_id == "dataset-public"
    assert methods == ["GET", "POST"]


@pytest.mark.asyncio
async def test_ensure_space_lists_visible_datasets_without_name_filter_and_paginates() -> None:
    requests: list[httpx.Request] = []
    first_page = [
        {"id": f"dataset-{index}", "name": f"other-{index}"}
        for index in range(100)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/v1/datasets"
        assert "name" not in request.url.params
        assert request.url.params["page_size"] == "100"
        page = int(request.url.params["page"] or "0")
        if page == 1:
            return httpx.Response(200, json={"code": 0, "data": first_page})
        assert page == 2
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [{"id": "dataset-target", "name": "client-a-project-alpha"}],
            },
        )

    async with httpx.AsyncClient(
        base_url="http://ragflow.local",
        transport=httpx.MockTransport(handler),
    ) as http:
        adapter = RagflowAdapter.from_http_client(http, api_key="secret")
        space = await adapter.ensure_space(
            EnsureKnowledgeSpaceRequest(
                project_id="PRJ-RETAIL-ALPHA",
                space_key="client-a-project-alpha",
            )
        )

    assert space.knowledge_space_id == "dataset-target"
    assert [request.url.params["page"] for request in requests] == ["1", "2"]
