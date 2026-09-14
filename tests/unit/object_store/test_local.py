from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import UUID

import pytest

from project_agent.application.ports.object_store import ObjectStorePort, PutObjectRequest
from project_agent.infrastructure.object_store.local import (
    LocalFileObjectStoreAdapter,
    ObjectStoreConflictError,
)

FIXED_UUID = UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.asyncio
async def test_local_store_round_trip_uses_uuid_path_and_persists_metadata(tmp_path: Path) -> None:
    store = LocalFileObjectStoreAdapter(tmp_path, uuid_factory=lambda: FIXED_UUID)
    assert isinstance(store, ObjectStorePort)

    payload = b"project source document"
    stored = await store.put(
        PutObjectRequest(
            project_id="project-alpha",
            object_key="source/design.md",
            data=payload,
            mime_type="text/markdown",
        )
    )

    assert stored.object_key == f"projects/project-alpha/objects/{FIXED_UUID}"
    assert stored.size_bytes == len(payload)
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert stored.mime_type == "text/markdown"

    object_dir = tmp_path / stored.object_key
    assert object_dir.is_dir()
    assert (object_dir / "payload.bin").read_bytes() == payload
    metadata = (object_dir / "metadata.json").read_text(encoding="utf-8")
    assert '"mime_type":"text/markdown"' in metadata
    assert f'"sha256":"{stored.sha256}"' in metadata
    assert '"logical_object_key":"source/design.md"' in metadata

    read_back = await store.get(stored.object_key)
    assert read_back.data == payload
    assert read_back.mime_type == "text/markdown"
    assert read_back.sha256 == stored.sha256
    assert await store.exists(stored.object_key) is True

    await store.delete(stored.object_key)
    assert await store.exists(stored.object_key) is False


@pytest.mark.asyncio
async def test_successful_put_leaves_no_partial_directory(tmp_path: Path) -> None:
    store = LocalFileObjectStoreAdapter(tmp_path, uuid_factory=lambda: FIXED_UUID)

    await store.put(
        PutObjectRequest(
            project_id="project-alpha",
            object_key="source/a.pdf",
            data=b"pdf",
            mime_type="application/pdf",
        )
    )

    partial = tmp_path / ".tmp" / f"{FIXED_UUID}.partial"
    assert partial.exists() is False


@pytest.mark.asyncio
async def test_duplicate_partial_write_is_rejected(tmp_path: Path) -> None:
    store = LocalFileObjectStoreAdapter(tmp_path, uuid_factory=lambda: FIXED_UUID)
    partial = tmp_path / ".tmp" / f"{FIXED_UUID}.partial"
    partial.mkdir(parents=True)
    (partial / "payload.bin").write_bytes(b"incomplete")

    with pytest.raises(ObjectStoreConflictError, match="partial write"):
        await store.put(
            PutObjectRequest(
                project_id="project-alpha",
                object_key="source/a.pdf",
                data=b"new",
                mime_type="application/pdf",
            )
        )

    assert (partial / "payload.bin").read_bytes() == b"incomplete"


@pytest.mark.asyncio
async def test_commit_failure_does_not_expose_partial_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalFileObjectStoreAdapter(tmp_path, uuid_factory=lambda: FIXED_UUID)
    storage_key = f"projects/project-alpha/objects/{FIXED_UUID}"

    def fail_replace(src: str | bytes | os.PathLike[str] | os.PathLike[bytes], dst: object) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        await store.put(
            PutObjectRequest(
                project_id="project-alpha",
                object_key="source/a.pdf",
                data=b"complete content",
                mime_type="application/pdf",
            )
        )

    assert (tmp_path / storage_key).exists() is False
    assert (tmp_path / ".tmp" / f"{FIXED_UUID}.partial").exists() is False


@pytest.mark.asyncio
async def test_missing_object_raises_file_not_found(tmp_path: Path) -> None:
    store = LocalFileObjectStoreAdapter(tmp_path)

    with pytest.raises(FileNotFoundError):
        await store.get("projects/project-alpha/objects/22222222-2222-4222-8222-222222222222")
