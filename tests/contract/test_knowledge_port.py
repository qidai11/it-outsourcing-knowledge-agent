from __future__ import annotations

import pytest

from project_agent.application.ports.knowledge import (
    EnsureKnowledgeSpaceRequest,
    IngestionState,
    KnowledgeAdminPort,
    KnowledgeIngestionPort,
    KnowledgeIngestionRequest,
    KnowledgeRetrievalPort,
    KnowledgeRetrievalRequest,
)
from tests.fakes.knowledge import FakeKnowledgePort


@pytest.mark.asyncio
async def test_fake_knowledge_port_implements_all_three_contracts() -> None:
    port = FakeKnowledgePort()

    assert isinstance(port, KnowledgeIngestionPort)
    assert isinstance(port, KnowledgeRetrievalPort)
    assert isinstance(port, KnowledgeAdminPort)

    space = await port.ensure_space(
        EnsureKnowledgeSpaceRequest(project_id="project-alpha", space_key="alpha-space")
    )
    receipt = await port.ingest(
        KnowledgeIngestionRequest(
            project_id="project-alpha",
            knowledge_space_id=space.knowledge_space_id,
            document_version_id="doc-v1",
            object_key="objects/doc-v1.pdf",
        )
    )

    status = await port.get_ingestion_status(receipt.ingestion_job_id)
    assert status.state is IngestionState.SUCCEEDED


@pytest.mark.asyncio
async def test_retrieval_returns_only_canonical_chunks_in_requested_project() -> None:
    port = FakeKnowledgePort()
    port.add_chunk(
        project_id="project-alpha",
        document_version_id="alpha-doc-v1",
        content="Alpha import endpoint uses UTF-8.",
        score=0.91,
        provider_ref="provider-alpha-1",
    )
    port.add_chunk(
        project_id="project-beta",
        document_version_id="beta-doc-v1",
        content="Beta import endpoint uses GBK.",
        score=0.99,
        provider_ref="provider-beta-1",
    )

    chunks = await port.retrieve(
        KnowledgeRetrievalRequest(
            project_id="project-alpha",
            query="import endpoint",
            limit=10,
        )
    )

    assert [chunk.document_version_id for chunk in chunks] == ["alpha-doc-v1"]
    assert all(chunk.project_id == "project-alpha" for chunk in chunks)
    assert all(not hasattr(chunk, "dataset_id") for chunk in chunks)
