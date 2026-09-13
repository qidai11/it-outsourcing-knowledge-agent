from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PutObjectRequest:
    project_id: str
    object_key: str
    data: bytes
    mime_type: str


@dataclass(frozen=True, slots=True)
class StoredObject:
    project_id: str
    object_key: str
    size_bytes: int
    sha256: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class ObjectPayload:
    object_key: str
    data: bytes
    mime_type: str
    sha256: str


@runtime_checkable
class ObjectStorePort(Protocol):
    async def put(self, request: PutObjectRequest) -> StoredObject: ...

    async def get(self, object_key: str) -> ObjectPayload: ...

    async def exists(self, object_key: str) -> bool: ...

    async def delete(self, object_key: str) -> None: ...
