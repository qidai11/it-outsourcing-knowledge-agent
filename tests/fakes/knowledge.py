from __future__ import annotations

from uuid import uuid4

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


class FakeKnowledgePort:
    def __init__(self) -> None:
        self._spaces: dict[tuple[str, str], KnowledgeSpace] = {}
        self._statuses: dict[str, KnowledgeIngestionStatus] = {}
        self._chunks: list[KnowledgeChunk] = []
        self.next_ingestion_state = IngestionState.SUCCEEDED
        self.fail_delete = False
        self.ingested_requests: list[KnowledgeIngestionRequest] = []
        self.retrieval_requests: list[KnowledgeRetrievalRequest] = []
        self.deleted_requests: list[DeleteKnowledgeDocumentRequest] = []

    async def ensure_space(self, request: EnsureKnowledgeSpaceRequest) -> KnowledgeSpace:
        key = (request.project_id, request.space_key)
        if key not in self._spaces:
            self._spaces[key] = KnowledgeSpace(
                knowledge_space_id=f"ks-{uuid4().hex}",
                project_id=request.project_id,
                space_key=request.space_key,
            )
        return self._spaces[key]

    async def ingest(self, request: KnowledgeIngestionRequest) -> KnowledgeIngestionReceipt:
        self.ingested_requests.append(request)
        job_id = f"ing-{uuid4().hex}"
        self._statuses[job_id] = KnowledgeIngestionStatus(
            ingestion_job_id=job_id,
            state=self.next_ingestion_state,
            error_code=(
                "SIMULATED_INGESTION_FAILURE"
                if self.next_ingestion_state is IngestionState.FAILED
                else None
            ),
        )
        self.next_ingestion_state = IngestionState.SUCCEEDED
        return KnowledgeIngestionReceipt(
            ingestion_job_id=job_id,
            project_id=request.project_id,
            document_version_id=request.document_version_id,
        )

    async def get_ingestion_status(self, ingestion_job_id: str) -> KnowledgeIngestionStatus:
        return self._statuses[ingestion_job_id]

    async def retrieve(self, request: KnowledgeRetrievalRequest) -> list[KnowledgeChunk]:
        self.retrieval_requests.append(request)
        allowed_versions = set(request.document_version_ids)
        allowed_spaces = set(request.knowledge_space_ids)
        results = [chunk for chunk in self._chunks if chunk.project_id == request.project_id]
        if allowed_versions:
            results = [chunk for chunk in results if chunk.document_version_id in allowed_versions]
        if allowed_spaces:
            results = [chunk for chunk in results if chunk.knowledge_space_id in allowed_spaces]
        results.sort(key=lambda chunk: chunk.score, reverse=True)
        return results[: request.limit]

    async def delete_document(self, request: DeleteKnowledgeDocumentRequest) -> None:
        self.deleted_requests.append(request)
        if self.fail_delete:
            raise RuntimeError("simulated knowledge delete failure")
        self._chunks = [
            chunk
            for chunk in self._chunks
            if not (
                chunk.project_id == request.project_id
                and chunk.document_version_id == request.document_version_id
            )
        ]


    def set_ingestion_state(
        self,
        ingestion_job_id: str,
        state: IngestionState,
        *,
        error_code: str | None = None,
    ) -> None:
        self._statuses[ingestion_job_id] = KnowledgeIngestionStatus(
            ingestion_job_id=ingestion_job_id,
            state=state,
            error_code=error_code,
        )

    def add_chunk(
        self,
        *,
        project_id: str,
        document_version_id: str,
        content: str,
        score: float,
        knowledge_space_id: str | None = None,
        provider_ref: str | None = None,
        page_no: int | None = None,
        section: str | None = None,
    ) -> None:
        self._chunks.append(
            KnowledgeChunk(
                project_id=project_id,
                document_version_id=document_version_id,
                knowledge_space_id=knowledge_space_id,
                content=content,
                score=score,
                provider_ref=provider_ref,
                page_no=page_no,
                section=section,
            )
        )
