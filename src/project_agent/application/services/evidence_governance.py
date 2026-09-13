from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol
from uuid import UUID

from project_agent.application.ports.knowledge import KnowledgeChunk
from project_agent.domain.enums import AuthorityLevel, DocumentCategory, DocumentLifecycleStatus
from project_agent.domain.evidence import GovernedEvidence, GovernedEvidencePack


@dataclass(frozen=True, slots=True)
class DocumentEvidenceMetadata:
    document_version_id: UUID
    document_id: UUID
    project_id: UUID
    document_category: DocumentCategory
    title: str
    authority_level: AuthorityLevel
    lifecycle_status: DocumentLifecycleStatus
    version_no: int
    version_label: str
    effective_from: date | None
    effective_to: date | None
    is_current: bool


class EvidenceGovernanceRepository(Protocol):
    async def get_document_evidence_metadata(
        self, *, document_version_ids: tuple[UUID, ...]
    ) -> dict[UUID, DocumentEvidenceMetadata]: ...


class EvidenceGovernanceService:
    AUTHORITY_ORDER = (
        AuthorityLevel.SIGNED_SCOPE,
        AuthorityLevel.APPROVED_CHANGE,
        AuthorityLevel.REQUIREMENT_BASELINE,
        AuthorityLevel.APPROVED_MEETING_MINUTES,
        AuthorityLevel.APPROVED_DESIGN,
        AuthorityLevel.APPROVED_TEST_SPEC,
        AuthorityLevel.RELEASE_RUNBOOK,
        AuthorityLevel.ISSUE_RECORD,
        AuthorityLevel.INFORMAL_NOTE,
    )
    _AUTHORITY_RANK = {value: index for index, value in enumerate(AUTHORITY_ORDER)}

    def __init__(
        self,
        repository: EvidenceGovernanceRepository,
        *,
        today: Callable[[], date] | None = None,
        max_evidence: int = 8,
    ) -> None:
        if max_evidence < 1:
            raise ValueError("max_evidence must be positive")
        self._repository = repository
        self._today = today or date.today
        self._max_evidence = max_evidence

    async def pack(
        self,
        *,
        project_id: UUID,
        project_code: str,
        chunks: list[KnowledgeChunk] | tuple[KnowledgeChunk, ...],
    ) -> GovernedEvidencePack:
        version_ids: list[UUID] = []
        parsed_chunks: list[tuple[KnowledgeChunk, UUID]] = []
        for chunk in chunks:
            if chunk.project_id != project_code:
                continue
            try:
                version_id = UUID(chunk.document_version_id)
            except (TypeError, ValueError):
                continue
            parsed_chunks.append((chunk, version_id))
            version_ids.append(version_id)

        metadata = await self._repository.get_document_evidence_metadata(
            document_version_ids=tuple(dict.fromkeys(version_ids))
        )
        today = self._today()
        candidates: list[GovernedEvidence] = []
        seen: set[tuple[UUID, str]] = set()
        for chunk, version_id in parsed_chunks:
            info = metadata.get(version_id)
            if info is None or info.project_id != project_id:
                continue
            if info.lifecycle_status is not DocumentLifecycleStatus.PUBLISHED or not info.is_current:
                continue
            if info.effective_from is not None and info.effective_from > today:
                continue
            if info.effective_to is not None and info.effective_to < today:
                continue
            dedupe_key = (version_id, chunk.content.strip())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            conflict_key = chunk.metadata.get("conflict_key") or None
            claim_value = chunk.metadata.get("claim_value") or None
            candidates.append(
                GovernedEvidence(
                    label="",
                    project_id=project_id,
                    project_code=project_code,
                    document_version_id=version_id,
                    document_category=info.document_category,
                    document_title=info.title,
                    version_no=info.version_no,
                    version_label=info.version_label,
                    authority_level=info.authority_level,
                    lifecycle_status=info.lifecycle_status,
                    is_current=info.is_current,
                    effective_from=info.effective_from,
                    effective_to=info.effective_to,
                    content=chunk.content,
                    score=chunk.score,
                    knowledge_space_id=chunk.knowledge_space_id,
                    provider_ref=chunk.provider_ref,
                    page_no=chunk.page_no,
                    section=chunk.section,
                    provider_metadata=dict(chunk.metadata),
                    conflict_key=conflict_key,
                    claim_value=claim_value,
                    unresolved_conflict=False,
                )
            )

        candidates = self._resolve_explicit_conflicts(candidates)
        candidates.sort(
            key=lambda item: (
                self._AUTHORITY_RANK[item.authority_level],
                -item.score,
                -item.version_no,
                str(item.document_version_id),
            )
        )
        selected = list(candidates[: self._max_evidence])
        protected_conflict_keys = {
            item.conflict_key
            for item in candidates
            if item.unresolved_conflict and item.conflict_key is not None
        }
        if protected_conflict_keys:
            selected_ids = {id(item) for item in selected}
            for item in candidates:
                if (
                    item.unresolved_conflict
                    and item.conflict_key in protected_conflict_keys
                    and id(item) not in selected_ids
                ):
                    selected.append(item)
                    selected_ids.add(id(item))
            selected.sort(
                key=lambda item: (
                    self._AUTHORITY_RANK[item.authority_level],
                    -item.score,
                    -item.version_no,
                    str(item.document_version_id),
                )
            )
        labeled = tuple(
            replace(item, label=f"E{index}") for index, item in enumerate(selected, 1)
        )

        by_conflict: dict[str, list[GovernedEvidence]] = defaultdict(list)
        for item in labeled:
            if item.unresolved_conflict and item.conflict_key:
                by_conflict[item.conflict_key].append(item)
        unresolved = {
            key: tuple(item.label for item in values)
            for key, values in sorted(by_conflict.items())
            if len({item.claim_value for item in values}) > 1
        }
        return GovernedEvidencePack(evidence=labeled, unresolved_conflicts=unresolved)

    def _resolve_explicit_conflicts(
        self, candidates: list[GovernedEvidence]
    ) -> list[GovernedEvidence]:
        groups: dict[str, list[GovernedEvidence]] = defaultdict(list)
        ungrouped: list[GovernedEvidence] = []
        for item in candidates:
            if item.conflict_key and item.claim_value is not None:
                groups[item.conflict_key].append(item)
            else:
                ungrouped.append(item)

        result = list(ungrouped)
        for values in groups.values():
            distinct_values = {item.claim_value for item in values}
            if len(distinct_values) <= 1:
                result.extend(values)
                continue
            best_rank = min(self._AUTHORITY_RANK[item.authority_level] for item in values)
            top = [item for item in values if self._AUTHORITY_RANK[item.authority_level] == best_rank]
            top_values = {item.claim_value for item in top}
            if len(top_values) == 1:
                result.extend(top)
            else:
                result.extend(replace(item, unresolved_conflict=True) for item in top)
        return result
