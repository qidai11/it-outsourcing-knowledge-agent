from __future__ import annotations

import hashlib

from project_agent.application.ports.object_store import (
    ObjectPayload,
    PutObjectRequest,
    StoredObject,
)


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, tuple[str, bytes, str]] = {}

    async def put(self, request: PutObjectRequest) -> StoredObject:
        digest = hashlib.sha256(request.data).hexdigest()
        self._objects[request.object_key] = (request.project_id, request.data, request.mime_type)
        return StoredObject(
            project_id=request.project_id,
            object_key=request.object_key,
            size_bytes=len(request.data),
            sha256=digest,
            mime_type=request.mime_type,
        )

    async def get(self, object_key: str) -> ObjectPayload:
        _project_id, data, mime_type = self._objects[object_key]
        return ObjectPayload(
            object_key=object_key,
            data=data,
            mime_type=mime_type,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    async def exists(self, object_key: str) -> bool:
        return object_key in self._objects

    async def delete(self, object_key: str) -> None:
        self._objects.pop(object_key, None)
