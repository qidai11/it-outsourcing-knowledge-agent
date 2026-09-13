from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.application.services.prompt_config import PromptSnapshot
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.evidence import (
    CitationReference,
    FrozenEvidence,
    FrozenEvidenceBundle,
    GovernedEvidencePack,
)
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    AnswerModel,
    CitationModel,
    EvidenceBundleModel,
    EvidenceSnapshotModel,
)


class SqlAlchemyQAGraphStore:
    """Persistence adapter for Task 10 graph artifacts.

    Graph checkpoints stay compact because nodes persist query analysis,
    retrieval plans, prompt snapshots and Evidence outside LangGraph state.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_query(self, run_id: UUID) -> str:
        stmt = (
            select(AgentEventModel.payload_json)
            .where(
                AgentEventModel.run_id == run_id,
                AgentEventModel.event_type == "USER_QUERY",
            )
            .order_by(AgentEventModel.sequence_no)
            .limit(1)
        )
        payload = (await self._session.execute(stmt)).scalar_one_or_none()
        if not isinstance(payload, dict):
            raise LookupError(f"run {run_id} has no USER_QUERY event")
        query = payload.get("query_text", payload.get("query"))
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"run {run_id} USER_QUERY event is missing query text")
        return query

    async def _next_sequence(self, run_id: UUID) -> int:
        run = await self._session.get(AgentRunModel, run_id, with_for_update=True)
        if run is None:
            raise LookupError(f"agent run does not exist: {run_id}")
        stmt = select(func.coalesce(func.max(AgentEventModel.sequence_no), 0)).where(
            AgentEventModel.run_id == run_id
        )
        return int((await self._session.execute(stmt)).scalar_one()) + 1

    async def save_artifact(
        self,
        *,
        run_id: UUID,
        artifact_type: str,
        payload: dict[str, object],
    ) -> UUID:
        event = AgentEventModel(
            run_id=run_id,
            sequence_no=await self._next_sequence(run_id),
            event_type=artifact_type,
            payload_json=payload,
        )
        self._session.add(event)
        await self._session.flush()
        return event.id

    async def load_artifact(self, artifact_id: UUID) -> dict[str, object]:
        event = await self._session.get(AgentEventModel, artifact_id)
        if event is None:
            raise LookupError(f"graph artifact does not exist: {artifact_id}")
        return dict(event.payload_json)

    async def record_prompt_snapshot(
        self,
        *,
        run_id: UUID,
        model_alias: str,
        snapshot: PromptSnapshot,
    ) -> UUID:
        run = await self._session.get(AgentRunModel, run_id, with_for_update=True)
        if run is None:
            raise LookupError(f"agent run does not exist: {run_id}")
        run.model_alias = model_alias
        run.prompt_version = str(snapshot.version)
        run.prompt_content_hash = snapshot.content_hash
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
        self,
        *,
        run_id: UUID,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token usage cannot be negative")
        run = await self._session.get(AgentRunModel, run_id, with_for_update=True)
        if run is None:
            raise LookupError(f"agent run does not exist: {run_id}")
        run.input_tokens += input_tokens
        run.output_tokens += output_tokens
        run.total_tokens += input_tokens + output_tokens

    async def increment_retrieval_rounds(self, *, run_id: UUID) -> None:
        run = await self._session.get(AgentRunModel, run_id, with_for_update=True)
        if run is None:
            raise LookupError(f"agent run does not exist: {run_id}")
        run.retrieval_rounds += 1

    async def save_evidence_bundle(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        query_text: str,
        chunks: list[KnowledgeChunk],
    ) -> UUID:
        bundle = EvidenceBundleModel(run_id=run_id, query_text=query_text)
        self._session.add(bundle)
        await self._session.flush()
        for rank, chunk in enumerate(chunks, start=1):
            metadata: dict[str, object] = dict(chunk.metadata)
            metadata.update(
                {
                    "project_code": chunk.project_id,
                    "knowledge_space_id": chunk.knowledge_space_id,
                    "page_no": chunk.page_no,
                    "section": chunk.section,
                }
            )
            self._session.add(
                EvidenceSnapshotModel(
                    bundle_id=bundle.id,
                    project_id=project_id,
                    document_version_id=UUID(chunk.document_version_id),
                    source_type="retrieval_candidate",
                    source_ref=chunk.provider_ref or f"retrieval:{rank}",
                    content=chunk.content,
                    rank=rank,
                    score=Decimal(str(chunk.score)),
                    metadata_json=metadata,
                )
            )
        await self._session.flush()
        return bundle.id

    async def load_evidence_bundle(self, bundle_id: UUID) -> tuple[KnowledgeChunk, ...]:
        stmt = (
            select(EvidenceSnapshotModel)
            .where(EvidenceSnapshotModel.bundle_id == bundle_id)
            .order_by(EvidenceSnapshotModel.rank)
        )
        rows = (await self._session.scalars(stmt)).all()
        result: list[KnowledgeChunk] = []
        for row in rows:
            metadata = dict(row.metadata_json)
            project_code = metadata.pop("project_code", None)
            knowledge_space_id = metadata.pop("knowledge_space_id", None)
            page_no = metadata.pop("page_no", None)
            section = metadata.pop("section", None)
            if not isinstance(project_code, str) or row.document_version_id is None:
                raise ValueError(f"evidence snapshot {row.id} is missing project/version mapping")
            result.append(
                KnowledgeChunk(
                    project_id=project_code,
                    document_version_id=str(row.document_version_id),
                    content=row.content,
                    score=float(row.score or 0),
                    knowledge_space_id=(
                        str(knowledge_space_id) if knowledge_space_id is not None else None
                    ),
                    provider_ref=row.source_ref,
                    page_no=int(page_no) if isinstance(page_no, int) else None,
                    section=str(section) if isinstance(section, str) else None,
                    metadata={str(key): str(value) for key, value in metadata.items()},
                )
            )
        return tuple(result)


    async def save_governed_evidence_bundle(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        query_text: str,
        pack: GovernedEvidencePack,
    ) -> UUID:
        bundle = EvidenceBundleModel(run_id=run_id, query_text=query_text)
        self._session.add(bundle)
        await self._session.flush()
        for rank, item in enumerate(pack.evidence, start=1):
            metadata: dict[str, object] = {
                "evidence_label": item.label,
                "project_code": item.project_code,
                "knowledge_space_id": item.knowledge_space_id,
                "page_no": item.page_no,
                "section": item.section,
                "document_version_id": str(item.document_version_id),
                "document_category": item.document_category.value,
                "document_title": item.document_title,
                "version_no": item.version_no,
                "version_label": item.version_label,
                "authority_level": item.authority_level.value,
                "lifecycle_status": item.lifecycle_status.value,
                "is_current": item.is_current,
                "effective_from": item.effective_from.isoformat() if item.effective_from else None,
                "effective_to": item.effective_to.isoformat() if item.effective_to else None,
                "content_hash": item.content_hash,
                "conflict_key": item.conflict_key,
                "claim_value": item.claim_value,
                "unresolved_conflict": item.unresolved_conflict,
                "provider_metadata": dict(item.provider_metadata),
            }
            self._session.add(
                EvidenceSnapshotModel(
                    bundle_id=bundle.id,
                    project_id=project_id,
                    document_version_id=item.document_version_id,
                    source_type="governed_evidence",
                    source_ref=item.provider_ref or item.label,
                    content=item.content,
                    rank=rank,
                    score=Decimal(str(item.score)),
                    metadata_json=metadata,
                )
            )
        await self._session.flush()
        return bundle.id

    async def load_governed_evidence_bundle(
        self, bundle_id: UUID
    ) -> FrozenEvidenceBundle:
        from datetime import date

        stmt = (
            select(EvidenceSnapshotModel)
            .where(
                EvidenceSnapshotModel.bundle_id == bundle_id,
                EvidenceSnapshotModel.source_type == "governed_evidence",
            )
            .order_by(EvidenceSnapshotModel.rank)
        )
        rows = (await self._session.scalars(stmt)).all()
        evidence: list[FrozenEvidence] = []
        conflicts: dict[str, list[str]] = {}
        for row in rows:
            metadata = dict(row.metadata_json)
            raw_version_id = row.document_version_id or metadata.get("document_version_id")
            if raw_version_id is None:
                raise ValueError(f"governed evidence {row.id} is missing document version")
            version_id = (
                raw_version_id
                if isinstance(raw_version_id, UUID)
                else UUID(str(raw_version_id))
            )
            label = metadata.get("evidence_label")
            project_code = metadata.get("project_code")
            if not isinstance(label, str) or not isinstance(project_code, str):
                raise ValueError(f"governed evidence {row.id} is missing label/project")
            conflict_key = metadata.get("conflict_key")
            unresolved = bool(metadata.get("unresolved_conflict", False))
            if unresolved and isinstance(conflict_key, str):
                conflicts.setdefault(conflict_key, []).append(label)
            raw_effective_from = metadata.get("effective_from")
            raw_effective_to = metadata.get("effective_to")
            evidence.append(
                FrozenEvidence(
                    snapshot_id=row.id,
                    label=label,
                    project_id=row.project_id,
                    project_code=project_code,
                    document_version_id=version_id,
                    document_category=DocumentCategory(str(metadata["document_category"])),
                    document_title=str(metadata["document_title"]),
                    version_no=int(metadata["version_no"]),
                    version_label=str(metadata["version_label"]),
                    authority_level=AuthorityLevel(str(metadata["authority_level"])),
                    lifecycle_status=DocumentLifecycleStatus(str(metadata["lifecycle_status"])),
                    is_current=bool(metadata["is_current"]),
                    effective_from=(
                        date.fromisoformat(str(raw_effective_from))
                        if raw_effective_from else None
                    ),
                    effective_to=(
                        date.fromisoformat(str(raw_effective_to))
                        if raw_effective_to else None
                    ),
                    content=row.content,
                    content_hash=str(metadata["content_hash"]),
                    score=float(row.score or 0),
                    knowledge_space_id=(
                        str(metadata["knowledge_space_id"])
                        if metadata.get("knowledge_space_id") is not None else None
                    ),
                    provider_ref=row.source_ref,
                    page_no=(
                        (
                            int(metadata["page_no"])
                            if isinstance(metadata.get("page_no"), int)
                            else None
                        )
                    ),
                    section=(
                        str(metadata["section"]) if metadata.get("section") is not None else None
                    ),
                    conflict_key=str(conflict_key) if conflict_key is not None else None,
                    claim_value=(
                        (
                            str(metadata["claim_value"])
                            if metadata.get("claim_value") is not None
                            else None
                        )
                    ),
                    unresolved_conflict=unresolved,
                )
            )
        return FrozenEvidenceBundle(
            evidence=tuple(evidence),
            unresolved_conflicts={key: tuple(values) for key, values in conflicts.items()},
        )

    async def save_grounded_answer(
        self,
        *,
        run_id: UUID,
        answer_text: str,
        citations: tuple[CitationReference, ...],
    ) -> UUID:
        answer_id = await self.save_answer(run_id=run_id, answer_text=answer_text)
        await self._session.execute(
            delete(CitationModel).where(CitationModel.answer_id == answer_id)
        )
        unique: dict[int, CitationReference] = {}
        for citation in citations:
            unique.setdefault(citation.citation_no, citation)
        for citation_no in sorted(unique):
            citation = unique[citation_no]
            self._session.add(
                CitationModel(
                    answer_id=answer_id,
                    evidence_snapshot_id=citation.evidence_snapshot_id,
                    citation_no=citation.citation_no,
                    quoted_text=None,
                )
            )
        await self._session.flush()
        return answer_id

    async def save_answer(
        self,
        *,
        run_id: UUID,
        answer_text: str,
        refusal_reason: str | None = None,
    ) -> UUID:
        existing = (
            await self._session.scalars(select(AnswerModel).where(AnswerModel.run_id == run_id))
        ).one_or_none()
        if existing is None:
            existing = AnswerModel(
                run_id=run_id,
                answer_text=answer_text,
                refusal_reason=refusal_reason,
            )
            self._session.add(existing)
        else:
            existing.answer_text = answer_text
            existing.refusal_reason = refusal_reason
        await self._session.flush()
        return existing.id
