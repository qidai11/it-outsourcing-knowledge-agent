from __future__ import annotations

from typing import Protocol
from uuid import UUID

from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.application.services.prompt_config import PromptSnapshot
from project_agent.domain.evidence import CitationReference, FrozenEvidenceBundle, GovernedEvidencePack


class QAGraphStorePort(Protocol):
    async def load_query(self, run_id: UUID) -> str: ...

    async def save_artifact(
        self,
        *,
        run_id: UUID,
        artifact_type: str,
        payload: dict[str, object],
    ) -> UUID: ...

    async def load_artifact(self, artifact_id: UUID) -> dict[str, object]: ...

    async def record_prompt_snapshot(
        self,
        *,
        run_id: UUID,
        model_alias: str,
        snapshot: PromptSnapshot,
    ) -> UUID: ...

    async def record_llm_usage(
        self,
        *,
        run_id: UUID,
        input_tokens: int,
        output_tokens: int,
    ) -> None: ...

    async def increment_retrieval_rounds(self, *, run_id: UUID) -> None: ...

    async def save_evidence_bundle(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        query_text: str,
        chunks: list[KnowledgeChunk],
    ) -> UUID: ...

    async def load_evidence_bundle(self, bundle_id: UUID) -> tuple[KnowledgeChunk, ...]: ...

    async def save_governed_evidence_bundle(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        query_text: str,
        pack: GovernedEvidencePack,
    ) -> UUID: ...

    async def load_governed_evidence_bundle(
        self, bundle_id: UUID
    ) -> FrozenEvidenceBundle: ...

    async def save_grounded_answer(
        self,
        *,
        run_id: UUID,
        answer_text: str,
        citations: tuple[CitationReference, ...],
    ) -> UUID: ...

    async def save_answer(
        self,
        *,
        run_id: UUID,
        answer_text: str,
        refusal_reason: str | None = None,
    ) -> UUID: ...
