from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import UUID, uuid4

from project_agent.application.ports.object_store import (
    ObjectPayload,
    PutObjectRequest,
    StoredObject,
)

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PAYLOAD_FILE = "payload.bin"
_METADATA_FILE = "metadata.json"


class ObjectStoreError(RuntimeError):
    """Base error for the local object-store adapter."""


class ObjectStoreSecurityError(ObjectStoreError, ValueError):
    """Raised when a key or filesystem layout could escape the configured root."""


class ObjectStoreConflictError(ObjectStoreError):
    """Raised when a UUID path or partial write already exists."""


class ObjectStoreCorruptionError(ObjectStoreError):
    """Raised when persisted metadata does not match the stored payload."""


class LocalFileObjectStoreAdapter:
    """Secure single-host source-file storage behind ``ObjectStorePort``.

    The caller-provided ``object_key`` is treated only as a logical source name.
    Physical storage uses an adapter-generated UUID directory:

    ``projects/{project_id}/objects/{uuid}/``

    A complete object is staged under ``.tmp/{uuid}.partial`` and atomically
    renamed into its final directory so readers never observe half-written
    payload/metadata pairs.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        configured_root = Path(root).expanduser()
        configured_root.mkdir(parents=True, exist_ok=True)
        self._root = configured_root.resolve(strict=True)
        self._uuid_factory = uuid_factory
        self._mkdir_safe((".tmp",))

    @property
    def root(self) -> Path:
        return self._root

    async def put(self, request: PutObjectRequest) -> StoredObject:
        return await asyncio.to_thread(self._put_sync, request)

    async def get(self, object_key: str) -> ObjectPayload:
        return await asyncio.to_thread(self._get_sync, object_key)

    async def exists(self, object_key: str) -> bool:
        return await asyncio.to_thread(self._exists_sync, object_key)

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._delete_sync, object_key)

    def _put_sync(self, request: PutObjectRequest) -> StoredObject:
        project_id = self._validate_project_id(request.project_id)
        logical_key = self._validate_logical_key(request.object_key)
        mime_type = self._validate_mime_type(request.mime_type)
        object_id = self._uuid_factory()
        if not isinstance(object_id, UUID):
            raise TypeError("uuid_factory must return uuid.UUID")

        storage_key = self._storage_key(project_id, object_id)
        final_parts = ("projects", project_id, "objects", str(object_id))
        final_parent = self._mkdir_safe(final_parts[:-1])
        final_dir = final_parent / final_parts[-1]
        self._reject_symlink(final_dir)
        if final_dir.exists():
            raise ObjectStoreConflictError(f"object UUID path already exists: {storage_key}")

        tmp_root = self._mkdir_safe((".tmp",))
        staging_dir = tmp_root / f"{object_id}.partial"
        self._reject_symlink(staging_dir)
        if staging_dir.exists():
            raise ObjectStoreConflictError(
                f"duplicate partial write exists for object UUID {object_id}"
            )

        digest = hashlib.sha256(request.data).hexdigest()
        metadata = {
            "project_id": project_id,
            "logical_object_key": logical_key,
            "storage_key": storage_key,
            "size_bytes": len(request.data),
            "sha256": digest,
            "mime_type": mime_type,
        }

        created_staging = False
        try:
            staging_dir.mkdir(mode=0o700)
            created_staging = True
            self._write_file_fsync(staging_dir / _PAYLOAD_FILE, request.data)
            metadata_bytes = json.dumps(
                metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            self._write_file_fsync(staging_dir / _METADATA_FILE, metadata_bytes)
            self._fsync_directory(staging_dir)

            # Directory rename is atomic on the same local filesystem. Both
            # payload and metadata become visible together.
            os.replace(staging_dir, final_dir)
            created_staging = False
            self._fsync_directory(final_parent)
        except BaseException:
            if created_staging and staging_dir.exists() and not staging_dir.is_symlink():
                shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        return StoredObject(
            project_id=project_id,
            object_key=storage_key,
            size_bytes=len(request.data),
            sha256=digest,
            mime_type=mime_type,
        )

    def _get_sync(self, object_key: str) -> ObjectPayload:
        object_dir = self._resolve_existing_object_dir(object_key)
        payload_path = object_dir / _PAYLOAD_FILE
        metadata_path = object_dir / _METADATA_FILE
        self._reject_symlink(payload_path)
        self._reject_symlink(metadata_path)

        if not payload_path.is_file() or not metadata_path.is_file():
            raise ObjectStoreCorruptionError(f"object bundle is incomplete: {object_key}")

        try:
            metadata_raw: Any = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ObjectStoreCorruptionError(f"invalid object metadata: {object_key}") from exc
        if not isinstance(metadata_raw, dict):
            raise ObjectStoreCorruptionError(f"invalid object metadata: {object_key}")

        data = payload_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        try:
            expected_digest = str(metadata_raw["sha256"])
            expected_size = int(metadata_raw["size_bytes"])
            mime_type = str(metadata_raw["mime_type"])
            metadata_key = str(metadata_raw["storage_key"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ObjectStoreCorruptionError(f"incomplete object metadata: {object_key}") from exc

        if metadata_key != object_key:
            raise ObjectStoreCorruptionError(f"storage key mismatch: {object_key}")
        if digest != expected_digest or len(data) != expected_size:
            raise ObjectStoreCorruptionError(f"payload checksum mismatch: {object_key}")

        return ObjectPayload(
            object_key=object_key,
            data=data,
            mime_type=mime_type,
            sha256=digest,
        )

    def _exists_sync(self, object_key: str) -> bool:
        project_id, object_id = self._parse_storage_key(object_key)
        parts = ("projects", project_id, "objects", str(object_id))
        path = self._root.joinpath(*parts)
        self._assert_ancestors_safe(parts, allow_missing=True)
        self._reject_symlink(path)
        return path.is_dir()

    def _delete_sync(self, object_key: str) -> None:
        try:
            object_dir = self._resolve_existing_object_dir(object_key)
        except FileNotFoundError:
            return
        self._reject_symlink(object_dir)
        shutil.rmtree(object_dir)
        self._fsync_directory(object_dir.parent)

    def _resolve_existing_object_dir(self, object_key: str) -> Path:
        project_id, object_id = self._parse_storage_key(object_key)
        parts = ("projects", project_id, "objects", str(object_id))
        self._assert_ancestors_safe(parts, allow_missing=True)
        object_dir = self._root.joinpath(*parts)
        self._reject_symlink(object_dir)
        if not object_dir.exists():
            raise FileNotFoundError(object_key)
        if not object_dir.is_dir():
            raise ObjectStoreSecurityError(f"object path is not a directory: {object_key}")
        self._assert_resolves_inside_root(object_dir)
        return object_dir

    def _mkdir_safe(self, parts: tuple[str, ...]) -> Path:
        current = self._root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ObjectStoreSecurityError(f"symlink component is not allowed: {current}")
            if current.exists():
                if not current.is_dir():
                    raise ObjectStoreSecurityError(f"path component is not a directory: {current}")
            else:
                current.mkdir(mode=0o700)
            self._assert_resolves_inside_root(current)
        return current

    def _assert_ancestors_safe(self, parts: tuple[str, ...], *, allow_missing: bool) -> None:
        current = self._root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ObjectStoreSecurityError(f"symlink component is not allowed: {current}")
            if current.exists():
                self._assert_resolves_inside_root(current)
                continue
            if allow_missing:
                return
            raise FileNotFoundError(current)

    def _assert_resolves_inside_root(self, path: Path) -> None:
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ObjectStoreSecurityError(f"path escape detected: {path}") from exc

    @staticmethod
    def _reject_symlink(path: Path) -> None:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode):
            raise ObjectStoreSecurityError(f"symlink path is not allowed: {path}")

    @staticmethod
    def _validate_project_id(project_id: str) -> str:
        if not _PROJECT_ID_RE.fullmatch(project_id):
            raise ObjectStoreSecurityError("project_id contains unsafe path characters")
        return project_id

    @staticmethod
    def _validate_logical_key(object_key: str) -> str:
        if not object_key or "\x00" in object_key:
            raise ObjectStoreSecurityError("object_key must be a non-empty relative key")
        if "\\" in object_key:
            raise ObjectStoreSecurityError("backslash paths are not allowed")
        path = PurePosixPath(object_key)
        windows_path = PureWindowsPath(object_key)
        if (
            path.is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ObjectStoreSecurityError("object_key must stay inside its logical namespace")
        return path.as_posix()

    @staticmethod
    def _validate_mime_type(mime_type: str) -> str:
        normalized = mime_type.strip()
        if not normalized or "\x00" in normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("mime_type must be a non-empty single-line value")
        return normalized

    @classmethod
    def _parse_storage_key(cls, object_key: str) -> tuple[str, UUID]:
        if not object_key or "\\" in object_key or "\x00" in object_key:
            raise ObjectStoreSecurityError("invalid storage object key")
        path = PurePosixPath(object_key)
        parts = path.parts
        if path.is_absolute() or len(parts) != 4 or parts[0] != "projects" or parts[2] != "objects":
            raise ObjectStoreSecurityError("invalid storage object key")
        project_id = cls._validate_project_id(parts[1])
        try:
            object_id = UUID(parts[3])
        except ValueError as exc:
            raise ObjectStoreSecurityError("storage object key must contain a UUID") from exc
        if str(object_id) != parts[3].lower():
            raise ObjectStoreSecurityError("storage object UUID must use canonical form")
        return project_id, object_id

    @staticmethod
    def _storage_key(project_id: str, object_id: UUID) -> str:
        return f"projects/{project_id}/objects/{object_id}"

    @staticmethod
    def _write_file_fsync(path: Path, data: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
