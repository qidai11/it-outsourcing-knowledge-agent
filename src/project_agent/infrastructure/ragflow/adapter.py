from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

import httpx

from project_agent.application.ports.knowledge import (
    DeleteKnowledgeDocumentRequest,
    EnsureKnowledgeSpaceRequest,
    IngestionState,
    KnowledgeChunk,
    KnowledgeIngestionReceipt,
    KnowledgeIngestionRequest,
    KnowledgeIngestionStatus,
    KnowledgeRetrievalRequest,
    KnowledgeSpace,
)
from project_agent.application.ports.object_store import ObjectStorePort
from project_agent.infrastructure.ragflow.baseline import (
    BASELINE_DATASET_BINDINGS,
    DOCUMENT_VERSION_METADATA_FIELD,
    PROJECT_METADATA_FIELD,
)
from project_agent.infrastructure.ragflow.client import RagflowHttpClient, RagflowRetryPolicy
from project_agent.infrastructure.ragflow.errors import (
    RagflowConfigurationError,
    RagflowProjectIsolationError,
    RagflowProtocolError,
)

_RESERVED_METADATA = {PROJECT_METADATA_FIELD, DOCUMENT_VERSION_METADATA_FIELD, "filename"}


@dataclass(frozen=True, slots=True)
class _DocumentMapping:
    project_id: str
    document_version_id: str
    metadata: dict[str, str]


class RagflowAdapter:
    """RAGFlow implementation of the application's knowledge ports.

    Dataset IDs are bound to one application project scope before use. Every
    uploaded document is stamped with application-owned metadata, and every
    retrieved provider chunk is mapped back to ``document_version_id`` before
    it can become a ``KnowledgeChunk``. Unmapped or cross-project chunks are
    discarded defensively.
    """

    def __init__(
        self,
        client: RagflowHttpClient,
        *,
        object_store: ObjectStorePort | None = None,
        embedding_model: str | None = None,
        chunk_method: str = "naive",
    ) -> None:
        self._client = client
        self._object_store = object_store
        self._embedding_model = embedding_model or None
        self._chunk_method = chunk_method
        self._space_to_project: dict[str, str] = {}
        self._project_to_spaces: dict[str, set[str]] = {}
        self._document_mappings: dict[tuple[str, str], _DocumentMapping] = {}

    @classmethod
    def from_http_client(
        cls,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        object_store: ObjectStorePort | None = None,
        embedding_model: str | None = None,
        chunk_method: str = "naive",
        retry_policy: RagflowRetryPolicy | None = None,
    ) -> RagflowAdapter:
        return cls(
            RagflowHttpClient(http, api_key=api_key, retry_policy=retry_policy),
            object_store=object_store,
            embedding_model=embedding_model,
            chunk_method=chunk_method,
        )

    def space_ids_for_project(self, project_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._project_to_spaces.get(project_id, set())))

    def bind_authorized_space(self, *, project_id: str, dataset_id: str) -> None:
        """Seed one DB-authorized dataset binding for Worker-side retrieval."""
        self._bind_space(project_id, dataset_id)

    async def ensure_space(self, request: EnsureKnowledgeSpaceRequest) -> KnowledgeSpace:
        self._validate_baseline_binding(request.project_id, request.space_key)
        existing = await self._find_visible_dataset_by_name(request.space_key)
        if existing is not None:
            dataset_id = self._required_string(existing, "id", context="dataset")
        else:
            payload: dict[str, Any] = {
                "name": request.space_key,
                "description": f"Managed by project-agent for scope {request.project_id}",
                "permission": "me",
                "chunk_method": self._chunk_method,
            }
            if self._embedding_model:
                payload["embedding_model"] = self._embedding_model
            created = await self._client.request_data("POST", "/api/v1/datasets", json=payload)
            if not isinstance(created, dict):
                raise RagflowProtocolError("create dataset response must be an object")
            dataset_id = self._required_string(created, "id", context="created dataset")

        self._bind_space(request.project_id, dataset_id)
        return KnowledgeSpace(dataset_id, request.project_id, request.space_key)

    async def _find_visible_dataset_by_name(self, name: str) -> dict[str, Any] | None:
        target = name.casefold()
        page = 1
        page_size = 100
        seen_ids: set[str] = set()
        while True:
            data = await self._client.request_data(
                "GET",
                "/api/v1/datasets",
                params={"page": page, "page_size": page_size},
            )
            datasets = self._dataset_list(data)
            for item in datasets:
                if str(item.get("name", "")).casefold() == target:
                    return item

            if len(datasets) < page_size:
                return None

            page_ids = {
                str(item.get("id"))
                for item in datasets
                if item.get("id") is not None
            }
            if page_ids and page_ids.issubset(seen_ids):
                raise RagflowProtocolError("list datasets pagination did not advance")
            seen_ids.update(page_ids)
            page += 1

    async def ingest(self, request: KnowledgeIngestionRequest) -> KnowledgeIngestionReceipt:
        self._bind_space(request.project_id, request.knowledge_space_id)
        if self._object_store is None:
            raise RagflowConfigurationError("Knowledge ingestion requires an ObjectStorePort")

        payload = await self._object_store.get(request.object_key)
        filename = self._safe_filename(
            request.metadata.get("filename") or f"{request.document_version_id}.bin"
        )
        uploaded = await self._client.request_data(
            "POST",
            f"/api/v1/datasets/{request.knowledge_space_id}/documents",
            files={"file": (filename, payload.data, payload.mime_type)},
        )
        if not isinstance(uploaded, list) or not uploaded or not isinstance(uploaded[0], dict):
            raise RagflowProtocolError("upload documents response must contain one document")
        provider_document_id = self._required_string(uploaded[0], "id", context="uploaded document")

        metadata = {
            key: str(value)
            for key, value in request.metadata.items()
            if key not in _RESERVED_METADATA
        }
        metadata[PROJECT_METADATA_FIELD] = request.project_id
        metadata[DOCUMENT_VERSION_METADATA_FIELD] = request.document_version_id

        try:
            await self._client.request_data(
                "PUT",
                f"/api/v1/datasets/{request.knowledge_space_id}/documents/{provider_document_id}",
                json={"meta_fields": metadata},
            )
        except BaseException:
            await self._best_effort_delete_provider_document(
                request.knowledge_space_id, provider_document_id
            )
            raise

        mapping_key = (request.knowledge_space_id, provider_document_id)
        self._document_mappings[mapping_key] = _DocumentMapping(
            request.project_id,
            request.document_version_id,
            {key: value for key, value in metadata.items() if key not in _RESERVED_METADATA},
        )
        await self._client.request_data(
            "POST",
            f"/api/v1/datasets/{request.knowledge_space_id}/chunks",
            json={"document_ids": [provider_document_id]},
        )

        return KnowledgeIngestionReceipt(
            ingestion_job_id=self._encode_ingestion_job_id(
                request.knowledge_space_id, provider_document_id
            ),
            project_id=request.project_id,
            document_version_id=request.document_version_id,
        )

    async def get_ingestion_status(self, ingestion_job_id: str) -> KnowledgeIngestionStatus:
        dataset_id, document_id = self._decode_ingestion_job_id(ingestion_job_id)
        document = await self._get_document(dataset_id, document_id)
        run = str(document.get("run", "")).upper()
        progress_message = document.get("progress_msg")
        if run in {"DONE", "SUCCEEDED", "SUCCESS"}:
            state = IngestionState.SUCCEEDED
            error = None
        elif run in {"FAIL", "FAILED", "ERROR", "CANCEL", "CANCELED", "CANCELLED"}:
            state = IngestionState.FAILED
            error = str(progress_message or run)
        elif run in {"RUNNING", "PARSING", "PROCESSING"}:
            state = IngestionState.RUNNING
            error = None
        else:
            state = IngestionState.PENDING
            error = None
        return KnowledgeIngestionStatus(ingestion_job_id, state, error)

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> list[KnowledgeChunk]:
        dataset_ids = self._dataset_ids_for_retrieval(request)
        data = await self._client.request_data(
            "POST",
            "/api/v1/retrieval",
            json={
                "question": request.query,
                "dataset_ids": list(dataset_ids),
                "document_ids": [],
                "page": 1,
                "page_size": max(1, min(max(request.limit * 2, 10), 100)),
                "metadata_condition": {
                    "logic": "and",
                    "conditions": [
                        {
                            "name": PROJECT_METADATA_FIELD,
                            "comparison_operator": "=",
                            "value": request.project_id,
                        }
                    ],
                },
            },
        )
        raw_chunks = data.get("chunks", []) if isinstance(data, dict) else []
        if not isinstance(raw_chunks, list):
            raise RagflowProtocolError("retrieval data.chunks must be a list")

        allowed_datasets = set(dataset_ids)
        requested_versions = set(request.document_version_ids)
        result: list[KnowledgeChunk] = []
        for raw in raw_chunks:
            if not isinstance(raw, dict):
                continue
            dataset_id = str(raw.get("dataset_id", ""))
            if dataset_id not in allowed_datasets:
                continue
            document_id = str(raw.get("document_id", ""))
            if not document_id:
                continue
            mapping = await self._resolve_document_mapping(dataset_id, document_id)
            if mapping is None or mapping.project_id != request.project_id:
                continue
            if requested_versions and mapping.document_version_id not in requested_versions:
                continue
            content = raw.get("content", raw.get("content_with_weight", ""))
            if not isinstance(content, str) or not content:
                continue
            score_raw = raw.get("similarity", 0.0)
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                score = 0.0
            provider_ref = str(raw.get("id")) if raw.get("id") is not None else None
            page_no = self._optional_int(mapping.metadata.get("page_no"))
            section = mapping.metadata.get("section")
            result.append(
                KnowledgeChunk(
                    project_id=request.project_id,
                    document_version_id=mapping.document_version_id,
                    content=content,
                    score=score,
                    knowledge_space_id=dataset_id,
                    provider_ref=provider_ref,
                    page_no=page_no,
                    section=section,
                    metadata=dict(mapping.metadata),
                )
            )
            if len(result) >= request.limit:
                break
        return result

    async def delete_document(self, request: DeleteKnowledgeDocumentRequest) -> None:
        self._bind_space(request.project_id, request.knowledge_space_id)
        documents = await self._list_documents(
            request.knowledge_space_id,
            metadata_condition={
                "logic": "and",
                "conditions": [
                    {
                        "name": PROJECT_METADATA_FIELD,
                        "comparison_operator": "=",
                        "value": request.project_id,
                    },
                    {
                        "name": DOCUMENT_VERSION_METADATA_FIELD,
                        "comparison_operator": "=",
                        "value": request.document_version_id,
                    },
                ],
            },
        )
        ids = [
            self._required_string(item, "id", context="document")
            for item in documents
            if self._mapping_from_document(item) == _DocumentMapping(
                request.project_id, request.document_version_id, self._public_metadata(item)
            )
        ]
        if not ids:
            return
        await self._client.request_data(
            "DELETE",
            f"/api/v1/datasets/{request.knowledge_space_id}/documents",
            json={"ids": ids},
        )
        for provider_document_id in ids:
            self._document_mappings.pop((request.knowledge_space_id, provider_document_id), None)

    def _dataset_ids_for_retrieval(self, request: KnowledgeRetrievalRequest) -> tuple[str, ...]:
        if request.knowledge_space_ids:
            for dataset_id in request.knowledge_space_ids:
                self._assert_space_for_project(request.project_id, dataset_id)
            return tuple(request.knowledge_space_ids)
        datasets = self.space_ids_for_project(request.project_id)
        if not datasets:
            raise RagflowConfigurationError(
                f"no RAGFlow dataset is bound to project {request.project_id!r}"
            )
        return datasets

    async def _resolve_document_mapping(
        self, dataset_id: str, document_id: str
    ) -> _DocumentMapping | None:
        key = (dataset_id, document_id)
        cached = self._document_mappings.get(key)
        if cached is not None:
            return cached
        document = await self._get_document(dataset_id, document_id)
        mapping = self._mapping_from_document(document)
        if mapping is not None:
            self._document_mappings[key] = mapping
        return mapping

    async def _get_document(self, dataset_id: str, document_id: str) -> dict[str, Any]:
        documents = await self._list_documents(dataset_id, document_id=document_id)
        for item in documents:
            if str(item.get("id", "")) == document_id:
                return item
        raise RagflowProtocolError(
            f"RAGFlow document {document_id!r} was not returned by dataset {dataset_id!r}"
        )

    async def _list_documents(
        self,
        dataset_id: str,
        *,
        document_id: str | None = None,
        metadata_condition: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page": 1, "page_size": 100}
        if document_id:
            params["id"] = document_id
        if metadata_condition is not None:
            params["metadata_condition"] = json.dumps(
                metadata_condition, ensure_ascii=False, separators=(",", ":")
            )
        data = await self._client.request_data(
            "GET", f"/api/v1/datasets/{dataset_id}/documents", params=params
        )
        if isinstance(data, dict):
            raw_docs = data.get("docs", [])
        elif isinstance(data, list):
            raw_docs = data
        else:
            raise RagflowProtocolError("list documents response has unexpected data shape")
        if not isinstance(raw_docs, list):
            raise RagflowProtocolError("list documents data.docs must be a list")
        return [item for item in raw_docs if isinstance(item, dict)]

    def _mapping_from_document(self, document: dict[str, Any]) -> _DocumentMapping | None:
        metadata = document.get("meta_fields")
        if not isinstance(metadata, dict):
            return None
        project_id = metadata.get(PROJECT_METADATA_FIELD)
        version_id = metadata.get(DOCUMENT_VERSION_METADATA_FIELD)
        if not isinstance(project_id, str) or not project_id:
            return None
        if not isinstance(version_id, str) or not version_id:
            return None
        public_metadata = {
            str(key): str(value)
            for key, value in metadata.items()
            if key not in {PROJECT_METADATA_FIELD, DOCUMENT_VERSION_METADATA_FIELD}
            and value is not None
        }
        return _DocumentMapping(project_id, version_id, public_metadata)

    def _public_metadata(self, document: dict[str, Any]) -> dict[str, str]:
        mapping = self._mapping_from_document(document)
        return {} if mapping is None else mapping.metadata

    async def _best_effort_delete_provider_document(
        self, dataset_id: str, document_id: str
    ) -> None:
        try:
            await self._client.request_data(
                "DELETE",
                f"/api/v1/datasets/{dataset_id}/documents",
                json={"ids": [document_id]},
            )
        except BaseException:
            return

    def _bind_space(self, project_id: str, dataset_id: str) -> None:
        existing = self._space_to_project.get(dataset_id)
        if existing is not None and existing != project_id:
            raise RagflowProjectIsolationError(
                f"RAGFlow dataset {dataset_id!r} is already bound to project {existing!r}"
            )
        self._space_to_project[dataset_id] = project_id
        self._project_to_spaces.setdefault(project_id, set()).add(dataset_id)

    def _assert_space_for_project(self, project_id: str, dataset_id: str) -> None:
        bound = self._space_to_project.get(dataset_id)
        if bound != project_id:
            raise RagflowProjectIsolationError(
                f"RAGFlow dataset {dataset_id!r} is not bound to project {project_id!r}"
            )

    @staticmethod
    def _validate_baseline_binding(project_id: str, space_key: str) -> None:
        for expected_project, expected_space in BASELINE_DATASET_BINDINGS.items():
            if expected_space == space_key and expected_project != project_id:
                raise RagflowProjectIsolationError(
                    f"baseline dataset {space_key!r} belongs to {expected_project!r}, "
                    f"not {project_id!r}"
                )

    @staticmethod
    def _dataset_list(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, list):
            raise RagflowProtocolError("list datasets response data must be a list")
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _required_string(item: dict[str, Any], field: str, *, context: str) -> str:
        value = item.get(field)
        if not isinstance(value, str) or not value:
            raise RagflowProtocolError(f"{context} is missing non-empty {field!r}")
        return value

    @staticmethod
    def _safe_filename(filename: str) -> str:
        if not filename or "\x00" in filename:
            raise RagflowConfigurationError("RAGFlow upload filename is invalid")
        if PurePosixPath(filename).name != filename or PureWindowsPath(filename).name != filename:
            raise RagflowConfigurationError("RAGFlow upload filename must not contain a path")
        if len(filename.encode("utf-8")) > 128:
            raise RagflowConfigurationError("RAGFlow upload filename exceeds 128 bytes")
        return filename

    @staticmethod
    def _encode_ingestion_job_id(dataset_id: str, document_id: str) -> str:
        return f"ragflow:{dataset_id}:{document_id}"

    @staticmethod
    def _decode_ingestion_job_id(ingestion_job_id: str) -> tuple[str, str]:
        parts = ingestion_job_id.split(":", 2)
        if len(parts) != 3 or parts[0] != "ragflow" or not parts[1] or not parts[2]:
            raise RagflowConfigurationError("invalid RAGFlow ingestion job id")
        return parts[1], parts[2]

    @staticmethod
    def _optional_int(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None
