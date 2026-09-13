from __future__ import annotations

import hashlib

import pytest

from project_agent.application.ports.object_store import ObjectStorePort, PutObjectRequest
from tests.fakes.object_store import InMemoryObjectStore


@pytest.mark.asyncio
async def test_in_memory_object_store_satisfies_contract_round_trip() -> None:
    store = InMemoryObjectStore()
    assert isinstance(store, ObjectStorePort)

    payload = b"project document"
    stored = await store.put(
        PutObjectRequest(
            project_id="project-alpha",
            object_key="source/doc-1.md",
            data=payload,
            mime_type="text/markdown",
        )
    )

    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    read_back = await store.get(stored.object_key)
    assert read_back.data == payload
    assert read_back.mime_type == "text/markdown"

    await store.delete(stored.object_key)
    assert await store.exists(stored.object_key) is False
