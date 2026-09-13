from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from project_agent.application.ports.object_store import PutObjectRequest
from project_agent.infrastructure.object_store.local import (
    LocalFileObjectStoreAdapter,
    ObjectStoreSecurityError,
)


FIXED_UUID = UUID("33333333-3333-4333-8333-333333333333")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "object_key",
    [
        "../secret.txt",
        "source/../../secret.txt",
        "/etc/passwd",
        "\\\\server\\share\\secret.txt",
        "C:\\Windows\\system.ini",
        "C:/Windows/system.ini",
    ],
)
async def test_put_rejects_unsafe_logical_object_keys(tmp_path: Path, object_key: str) -> None:
    store = LocalFileObjectStoreAdapter(tmp_path, uuid_factory=lambda: FIXED_UUID)

    with pytest.raises(ObjectStoreSecurityError):
        await store.put(
            PutObjectRequest(
                project_id="project-alpha",
                object_key=object_key,
                data=b"x",
                mime_type="text/plain",
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "object_key",
    [
        "../etc/passwd",
        "/etc/passwd",
        "projects/project-alpha/objects/not-a-uuid",
        "projects/project-alpha/objects/33333333-3333-4333-8333-333333333333/../../etc",
    ],
)
async def test_get_delete_and_exists_reject_non_storage_keys(
    tmp_path: Path, object_key: str
) -> None:
    store = LocalFileObjectStoreAdapter(tmp_path)

    with pytest.raises(ObjectStoreSecurityError):
        await store.get(object_key)
    with pytest.raises(ObjectStoreSecurityError):
        await store.exists(object_key)
    with pytest.raises(ObjectStoreSecurityError):
        await store.delete(object_key)


@pytest.mark.asyncio
async def test_put_rejects_project_directory_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "project-alpha").symlink_to(outside, target_is_directory=True)

    store = LocalFileObjectStoreAdapter(tmp_path, uuid_factory=lambda: FIXED_UUID)

    with pytest.raises(ObjectStoreSecurityError, match="escape|symlink"):
        await store.put(
            PutObjectRequest(
                project_id="project-alpha",
                object_key="source/a.pdf",
                data=b"x",
                mime_type="application/pdf",
            )
        )

    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_get_and_delete_reject_object_directory_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-object"
    outside.mkdir()
    (outside / "payload.bin").write_bytes(b"secret")

    object_dir = tmp_path / "projects/project-alpha/objects" / str(FIXED_UUID)
    object_dir.parent.mkdir(parents=True)
    object_dir.symlink_to(outside, target_is_directory=True)

    store = LocalFileObjectStoreAdapter(tmp_path)
    key = f"projects/project-alpha/objects/{FIXED_UUID}"

    with pytest.raises(ObjectStoreSecurityError, match="symlink|escape"):
        await store.get(key)
    with pytest.raises(ObjectStoreSecurityError, match="symlink|escape"):
        await store.delete(key)
