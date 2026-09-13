from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.domain.evidence import CitationReference, FrozenEvidence, FrozenEvidenceBundle, GovernedEvidencePack
from project_agent.application.services.prompt_config import PromptSnapshot


@dataclass(slots=True)
class FakeRunTelemetry:
    model_alias: str | None = None
    prompt_version: str | None = None
    prompt_content_hash: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    retrieval_rounds: int = 0


class InMemoryQAGraphStore:
    def __init__(self) -> None:
        self.queries: dict[UUID, str] = {}
        self.artifacts: dict[UUID, dict[str, object]] = {}
        self.bundles: dict[UUID, tuple[KnowledgeChunk, ...]] = {}
        self.answers: dict[UUID, dict[str, object]] = {}
        self.governed_bundles: dict[UUID, FrozenEvidenceBundle] = {}
        self.citations: dict[UUID, tuple[CitationReference, ...]] = {}
        self.telemetry: dict[UUID, FakeRunTelemetry] = {}

    def seed_query(self, run_id: UUID, query: str) -> None:
        self.queries[run_id] = query
        self.telemetry.setdefault(run_id, FakeRunTelemetry())

    async def load_query(self, run_id: UUID) -> str:
        return self.queries[run_id]

    async def save_artifact(
        self, *, run_id: UUID, artifact_type: str, payload: dict[str, object]
    ) -> UUID:
        artifact_id = uuid4()
        self.artifacts[artifact_id] = {
            "run_id": str(run_id),
            "artifact_type": artifact_type,
            "payload": payload,
        }
        return artifact_id

    async def load_artifact(self, artifact_id: UUID) -> dict[str, object]:
        record = self.artifacts[artifact_id]
        return dict(record["payload"])  # type: ignore[arg-type]

    async def record_prompt_snapshot(
        self, *, run_id: UUID, model_alias: str, snapshot: PromptSnapshot
    ) -> UUID:
        telemetry = self.telemetry.setdefault(run_id, FakeRunTelemetry())
        telemetry.model_alias = model_alias
        telemetry.prompt_version = str(snapshot.version)
        telemetry.prompt_content_hash = snapshot.content_hash
        return await self.save_artifact(
            run_id=run_id,
            artifact_type="PROMPT_SNAPSHOT",
            payload={
                "config_key": snapshot.config_key,
                "content": snapshot.content,
                "version": snapshot.version,
                "content_hash": snapshot.content_hash,
            },
        )

    async def record_llm_usage(
        self, *, run_id: UUID, input_tokens: int, output_tokens: int
    ) -> None:
        telemetry = self.telemetry.setdefault(run_id, FakeRunTelemetry())
        telemetry.input_tokens += input_tokens
        telemetry.output_tokens += output_tokens
        telemetry.total_tokens += input_tokens + output_tokens

    async def increment_retrieval_rounds(self, *, run_id: UUID) -> None:
        telemetry = self.telemetry.setdefault(run_id, FakeRunTelemetry())
        telemetry.retrieval_rounds += 1

    async def save_evidence_bundle(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        query_text: str,
        chunks: list[KnowledgeChunk],
    ) -> UUID:
        bundle_id = uuid4()
        self.bundles[bundle_id] = tuple(chunks)
        return bundle_id

    async def load_evidence_bundle(self, bundle_id: UUID) -> tuple[KnowledgeChunk, ...]:
        return self.bundles[bundle_id]


    async def save_governed_evidence_bundle(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        query_text: str,
        pack: GovernedEvidencePack,
    ) -> UUID:
        bundle_id = uuid4()
        frozen = tuple(
            FrozenEvidence(
                snapshot_id=uuid4(),
                label=item.label,
                project_id=item.project_id,
                project_code=item.project_code,
                document_version_id=item.document_version_id,
                document_category=item.document_category,
                document_title=item.document_title,
                version_no=item.version_no,
                version_label=item.version_label,
                authority_level=item.authority_level,
                lifecycle_status=item.lifecycle_status,
                is_current=item.is_current,
                effective_from=item.effective_from,
                effective_to=item.effective_to,
                content=item.content,
                content_hash=item.content_hash,
                score=item.score,
                knowledge_space_id=item.knowledge_space_id,
                provider_ref=item.provider_ref,
                page_no=item.page_no,
                section=item.section,
                conflict_key=item.conflict_key,
                claim_value=item.claim_value,
                unresolved_conflict=item.unresolved_conflict,
            )
            for item in pack.evidence
        )
        self.governed_bundles[bundle_id] = FrozenEvidenceBundle(
            evidence=frozen, unresolved_conflicts=dict(pack.unresolved_conflicts)
        )
        return bundle_id

    async def load_governed_evidence_bundle(self, bundle_id: UUID) -> FrozenEvidenceBundle:
        return self.governed_bundles[bundle_id]

    async def save_grounded_answer(
        self,
        *,
        run_id: UUID,
        answer_text: str,
        citations: tuple[CitationReference, ...],
    ) -> UUID:
        answer_id = await self.save_answer(run_id=run_id, answer_text=answer_text)
        self.citations[answer_id] = citations
        return answer_id

    async def save_answer(
        self,
        *,
        run_id: UUID,
        answer_text: str,
        refusal_reason: str | None = None,
    ) -> UUID:
        answer_id = uuid4()
        self.answers[answer_id] = {
            "run_id": str(run_id),
            "answer_text": answer_text,
            "refusal_reason": refusal_reason,
        }
        return answer_id
