"""WS8 raw trial collection from persisted runtime facts, without scoring or writes.

The SQL reader is deliberately a separate seam: unit tests supply persisted-shaped
rows, while the live gate uses this reader against the isolated evaluation database.
Never infer retrieval order from UUIDs or timestamps or document identities from titles.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from project_agent.evaluation.artifacts import SecretArtifactError, _assert_secret_safe
from project_agent.evaluation.models import (
    CitationArtifact,
    EvaluationCase,
    EvidenceArtifact,
    IssueArtifact,
    RetrievalRoundArtifact,
    TrialArtifact,
    TrialClassification,
)
from project_agent.infrastructure.db.models.schema import (
    AgentEventModel,
    AgentRunModel,
    AnswerModel,
    CitationModel,
    DocumentModel,
    DocumentVersionModel,
    EvidenceBundleModel,
    EvidenceSnapshotModel,
    IdempotencyRecordModel,
    IssueCandidateModel,
    IssueDraftModel,
    SandboxIssueEventModel,
    SandboxIssueModel,
    ToolConfirmationModel,
)


@dataclass(frozen=True, slots=True)
class RunObservation:
    """Transport/scenario facts supplied by Task 4; never store request headers."""

    trial_no: int
    run_id: UUID | None = None
    business_mode: str | None = None
    http_status: int | None = None
    classification: TrialClassification = TrialClassification.SCORED
    request_id: str | None = None
    reconciliation_outcome: str | None = None
    error_category: str | None = None


@dataclass(frozen=True, slots=True)
class SideEffectSnapshot:
    """Request-scoped count captured before or after a trial, not all project issues."""

    count: int
    project_id: UUID | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class RunFacts:
    """Persisted-shaped read model; Any keeps the seam compatible with ORM and fakes."""

    run: Any = None
    events: tuple[Any, ...] = ()
    snapshots: tuple[Any, ...] = ()
    documents: Mapping[UUID, Any] | None = None
    answer: Any = None
    citations: tuple[Any, ...] = ()
    draft: Any = None
    issue_candidates: tuple[tuple[Any, Any], ...] = ()
    confirmations: tuple[Any, ...] = ()
    idempotency: Any = None
    sandbox_issues: tuple[Any, ...] = ()
    sandbox_events: tuple[Any, ...] = ()


class TrialReader(Protocol):
    async def read(
        self, *, run_id: UUID, project_id: UUID, request_id: str | None
    ) -> RunFacts: ...


class SqlAlchemyTrialReader:
    """Read-only, project-scoped snapshot of durable Task 3 facts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def capture_side_effects(
        self, *, project_id: UUID, request_id: str
    ) -> SideEffectSnapshot:
        if not request_id:
            raise ValueError("evaluation request_id is required for side-effect counting")
        count = await self._session.scalar(
            select(func.count(SandboxIssueModel.id)).where(
                SandboxIssueModel.project_id == project_id,
                SandboxIssueModel.client_request_id == request_id,
            )
        )
        return SideEffectSnapshot(
            count=int(count or 0), project_id=project_id, request_id=request_id
        )

    async def read(
        self, *, run_id: UUID, project_id: UUID, request_id: str | None
    ) -> RunFacts:
        session = self._session
        run = await session.get(AgentRunModel, run_id)
        if run is None:
            raise LookupError("evaluation run not found")
        if run.project_id != project_id:
            raise ValueError("evaluation run belongs to a different project")
        events = tuple(
            (await session.scalars(
                select(AgentEventModel).where(AgentEventModel.run_id == run_id)
                .order_by(AgentEventModel.sequence_no)
            )).all()
        )
        snapshots = tuple(
            (await session.scalars(
                select(EvidenceSnapshotModel)
                .join(
                    EvidenceBundleModel,
                    EvidenceSnapshotModel.bundle_id == EvidenceBundleModel.id,
                )
                .where(EvidenceBundleModel.run_id == run_id,
                       EvidenceSnapshotModel.project_id == project_id)
            )).all()
        )
        version_ids = {s.document_version_id for s in snapshots if s.document_version_id}
        documents: dict[UUID, Any] = {}
        if version_ids:
            rows = (await session.execute(
                select(DocumentVersionModel, DocumentModel)
                .join(DocumentModel, DocumentVersionModel.document_id == DocumentModel.id)
                .where(DocumentVersionModel.id.in_(version_ids),
                       DocumentModel.project_id == project_id)
            )).all()
            document_ids = {version.document_id for version, _document in rows}
            current_versions: dict[UUID, int] = {}
            if document_ids:
                current_versions = {
                    doc_id: int(version_no)
                    for doc_id, version_no in (await session.execute(
                        select(DocumentVersionModel.document_id,
                               func.max(DocumentVersionModel.version_no))
                        .where(DocumentVersionModel.document_id.in_(document_ids),
                               DocumentVersionModel.lifecycle_status == "PUBLISHED")
                        .group_by(DocumentVersionModel.document_id)
                    )).all()
                }
            for version, document in rows:
                documents[version.id] = (
                    version, document, current_versions.get(version.document_id)
                )
        answer = (await session.scalars(
            select(AnswerModel).where(AnswerModel.run_id == run_id)
        )).one_or_none()
        citations: tuple[Any, ...] = ()
        if answer is not None:
            citations = tuple((await session.scalars(
                select(CitationModel).where(CitationModel.answer_id == answer.id)
                .order_by(CitationModel.citation_no)
            )).all())
        draft = (await session.scalars(
            select(IssueDraftModel).where(
                IssueDraftModel.run_id == run_id, IssueDraftModel.project_id == project_id
            ).order_by(IssueDraftModel.created_at.desc(), IssueDraftModel.id.desc())
            .limit(1)
        )).one_or_none()
        issue_candidates: tuple[tuple[Any, Any], ...] = ()
        if draft is not None:
            issue_rows = (await session.execute(
                select(IssueCandidateModel, SandboxIssueModel)
                .join(SandboxIssueModel,
                      SandboxIssueModel.id == IssueCandidateModel.sandbox_issue_id)
                .where(IssueCandidateModel.issue_draft_id == draft.id,
                       SandboxIssueModel.project_id == project_id)
                .order_by(IssueCandidateModel.rank, SandboxIssueModel.issue_key)
            )).all()
            issue_candidates = tuple((candidate, issue) for candidate, issue in issue_rows)
        confirmations = tuple((await session.scalars(
            select(ToolConfirmationModel).where(ToolConfirmationModel.run_id == run_id)
            .order_by(ToolConfirmationModel.created_at, ToolConfirmationModel.id)
        )).all())
        idempotency = None
        sandbox_issues: tuple[Any, ...] = ()
        sandbox_events: tuple[Any, ...] = ()
        if request_id is not None:
            idempotency = (await session.scalars(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.namespace == "sandbox_issue_create",
                    IdempotencyRecordModel.request_id == request_id,
                    IdempotencyRecordModel.project_id == project_id,
                )
            )).one_or_none()
            sandbox_issues = tuple((await session.scalars(
                select(SandboxIssueModel).where(
                    SandboxIssueModel.project_id == project_id,
                    SandboxIssueModel.client_request_id == request_id,
                ).order_by(SandboxIssueModel.issue_key)
            )).all())
            issue_ids = [item.id for item in sandbox_issues]
            if issue_ids:
                sandbox_events = tuple((await session.scalars(
                    select(SandboxIssueEventModel).where(
                        SandboxIssueEventModel.sandbox_issue_id.in_(issue_ids)
                    ).order_by(SandboxIssueEventModel.created_at,
                               SandboxIssueEventModel.id)
                )).all())
        return RunFacts(
            run=run, events=events, snapshots=snapshots, documents=documents,
            answer=answer, citations=citations, draft=draft,
            issue_candidates=issue_candidates, confirmations=confirmations,
            idempotency=idempotency, sandbox_issues=sandbox_issues,
            sandbox_events=sandbox_events,
        )


_SAFE_ERROR = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_\s-]?key|access[_\s-]?token|password|secret)\s*[:=]\s*\S+"
)
_CREDENTIAL_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/@\s:]+:[^/@\s]+@")
_PROVIDER_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    if (_SECRET_ASSIGNMENT.search(value) or _CREDENTIAL_URL.search(value)
            or _PROVIDER_KEY.search(value)):
        return "[REDACTED]"
    try:
        _assert_secret_safe(value)
    except SecretArtifactError:
        return "[REDACTED]"
    return value


def _safe_identifier(value: Any) -> str | None:
    text = _text(value)
    return text if text and text != "[REDACTED]" else None


def _date(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _event_status(event: str) -> str | None:
    return {
        "RUN_QUEUED": "QUEUED",
        "RUN_STARTED": "RUNNING",
        "RUN_RESUME_QUEUED": "QUEUED",
        "RUN_RESUMED": "RUNNING",
        "WAITING_CONFIRMATION": "WAITING_CONFIRMATION",
        "RUN_SUCCEEDED": "SUCCEEDED",
        "RUN_COMPLETED": "SUCCEEDED",  # compatible with historical event fixtures
        "RUN_REFUSED": "REFUSED",
        "RUN_CANCELLED": "CANCELLED",
        "RUN_FAILED": "FAILED",
    }.get(event)


def _artifact_metadata(events: tuple[Any, ...]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for event in events:
        if event.event_type != "ARTIFACT_AVAILABLE":
            continue
        payload = event.payload_json
        artifact = payload.get("artifact")
        if not isinstance(artifact, dict):
            continue
        if payload.get("artifact_type") == "ANSWER_DRAFT":
            metadata["answer_draft_present"] = True
            # No free-text answer draft or model prompt enters raw metrics metadata.
        elif payload.get("artifact_type") == "CITATION_GUARD":
            guard = {
                key: artifact[key] for key in ("valid", "coverage", "coverage_ok")
                if key in artifact and isinstance(artifact[key], (bool, int, float))
            }
            used = artifact.get("used_evidence_ids")
            if isinstance(used, list):
                guard["used_evidence_ids"] = [
                    value for value in used if isinstance(value, str)
                    and _safe_identifier(value) is not None
                ]
            history = metadata.setdefault("citation_guard_history", [])
            if isinstance(history, list):
                history.append(guard)
            metadata["citation_guard"] = guard
    return metadata


def _evidence(
    row: Any, *, version_to_code: Mapping[str, str],
    documents: Mapping[UUID, Any], expected_project_code: str,
    expected_project_id: UUID,
) -> EvidenceArtifact:
    if row.project_id != expected_project_id:
        raise ValueError("evaluation evidence belongs to a different project")
    version = row.document_version_id
    meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    doc_pair = documents.get(version)
    version_row, document_row, current_version_no = (
        doc_pair if doc_pair is not None else (None, None, None)
    )
    if document_row is not None and document_row.project_id != expected_project_id:
        raise ValueError("evaluation evidence document belongs to a different project")
    lifecycle = meta.get("lifecycle_status")
    if lifecycle is None and version_row is not None:
        lifecycle = version_row.lifecycle_status
    is_current = meta.get("is_current")
    if is_current is None and version_row is not None:
        is_current = (
            version_row.lifecycle_status == "PUBLISHED"
            and current_version_no == version_row.version_no
        )
    project_code = meta.get("project_code")
    if project_code is not None and project_code != expected_project_code:
        raise ValueError("evaluation evidence metadata has a different project")
    if project_code is None:
        project_code = expected_project_code
    safe_meta: dict[str, Any] = {}
    for name in (
        "authority_level", "document_category", "version_no", "version_label",
        "unresolved_conflict", "conflict_key", "content_hash", "evidence_label",
    ):
        value = meta.get(name)
        if isinstance(value, (str, int, bool)):
            safe_meta[name] = _text(value) if isinstance(value, str) else value
    if row.score is not None:
        safe_meta["score"] = float(row.score)
    return EvidenceArtifact(
        evidence_id=str(row.id),
        doc_code=version_to_code.get(str(version)) if version is not None else None,
        project_code=_safe_identifier(project_code), rank=row.rank,
        document_version_id=str(version) if version is not None else None,
        lifecycle_status=_safe_identifier(lifecycle),
        is_current=is_current if isinstance(is_current, bool) else None,
        metadata=safe_meta,
    )


class TrialCollector:
    """Assemble scorer inputs. No metric decision, DB mutation, or secret-bearing logs."""

    def __init__(self, reader: TrialReader) -> None:
        self._reader = reader

    async def collect(
        self,
        *,
        case: EvaluationCase,
        run_observation: RunObservation,
        fixture_state: Mapping[str, Any],
        before_state: SideEffectSnapshot,
        after_state: SideEffectSnapshot,
    ) -> TrialArtifact:
        if run_observation.trial_no < 1:
            raise ValueError("trial_no must be positive")
        project_ids = fixture_state.get("project_ids", {})
        project_id_raw = project_ids.get(case.project_code)
        if project_id_raw is None:
            raise ValueError("run project is absent from evaluation fixture state")
        # fixture-state.json is persisted JSON, so UUID-valued IDs are strings after
        # reload. PostgreSQL rows and SideEffectSnapshot retain real UUID objects.
        # Normalize exactly once at the collector boundary before scope comparisons.
        project_id = UUID(str(project_id_raw))
        if before_state.count < 0 or after_state.count < 0:
            raise ValueError("side-effect counts must be nonnegative")
        request_id = _safe_identifier(run_observation.request_id)
        for captured in (before_state, after_state):
            if captured.request_id is not None and captured.request_id != request_id:
                raise ValueError("side-effect capture request does not match the trial")
            if captured.project_id is not None and captured.project_id != project_id:
                raise ValueError("side-effect capture project does not match the trial")
        if run_observation.request_id is not None and request_id is None:
            raise ValueError("unsafe evaluation request_id")
        facts = RunFacts()
        if run_observation.run_id is not None:
            facts = await self._reader.read(
                run_id=run_observation.run_id,
                project_id=project_id, request_id=request_id,
            )
            if facts.run is None:
                raise LookupError("collector reader did not return a run")
            if facts.run.project_id != project_id:
                raise ValueError("evaluation run belongs to a different project")
            expected_user = fixture_state.get("user_ids", {}).get(case.user_alias)
            if expected_user is not None and facts.run.user_id != UUID(str(expected_user)):
                raise ValueError("evaluation run belongs to a different user")
        run = facts.run
        events = tuple(sorted(facts.events, key=lambda event: event.sequence_no))
        statuses: list[str] = []
        for event in events:
            status = _event_status(event.event_type)
            if status is not None and (not statuses or statuses[-1] != status):
                statuses.append(status)
        if run is not None and (not statuses or statuses[-1] != run.status):
            statuses.append(run.status)
        version_to_code = {
            str(value): str(code)
            for code, value in fixture_state.get("document_version_ids", {}).items()
        }
        documents = facts.documents or {}
        rounds: dict[int, list[EvidenceArtifact]] = defaultdict(list)
        governed: list[EvidenceArtifact] = []
        snapshot_by_id: dict[str, EvidenceArtifact] = {}
        for row in facts.snapshots:
            if row.project_id != project_id:
                raise ValueError("evaluation evidence belongs to a different project")
            if row.source_type in {"retrieval_candidate", "retrieval_round_marker"}:
                number = row.metadata_json.get("retrieval_round")
                if type(number) is not int or number < 1:
                    raise ValueError("retrieval_round must be a positive persisted integer")
                if row.source_type == "retrieval_round_marker":
                    rounds.setdefault(number, [])  # empty round must remain visible
                else:
                    artifact = _evidence(row, version_to_code=version_to_code,
                                         documents=documents,
                                         expected_project_code=case.project_code,
                                         expected_project_id=project_id)
                    rounds[number].append(artifact)
                    snapshot_by_id[artifact.evidence_id] = artifact
            elif row.source_type == "governed_evidence":
                artifact = _evidence(row, version_to_code=version_to_code,
                                     documents=documents,
                                     expected_project_code=case.project_code,
                                     expected_project_id=project_id)
                governed.append(artifact)
                snapshot_by_id[artifact.evidence_id] = artifact
        retrieval_rounds = tuple(
            RetrievalRoundArtifact(round_no=number, candidates=tuple(
                sorted(rounds[number], key=lambda item: (
                    item.rank if item.rank is not None else 999999, item.evidence_id
                ))
            )) for number in sorted(rounds)
        )
        governed.sort(key=lambda item: (item.rank or 999999, item.evidence_id))
        citations = tuple(CitationArtifact(
            citation_id=str(row.id), evidence_id=str(row.evidence_snapshot_id),
            doc_code=(snapshot_by_id[str(row.evidence_snapshot_id)].doc_code
                      if str(row.evidence_snapshot_id) in snapshot_by_id else None),
            metadata={"citation_no": row.citation_no},
        ) for row in sorted(facts.citations, key=lambda citation: citation.citation_no))
        metadata = _artifact_metadata(events)
        draft = facts.draft
        issues = facts.sandbox_issues
        candidate_keys = [issue.issue_key for _candidate, issue in facts.issue_candidates]
        business_mode = (
            str(run.business_mode) if run is not None and run.business_mode
            else (run_observation.business_mode or case.question_type)
        )
        is_issue = bool(
            draft or facts.confirmations or facts.idempotency or issues
            or before_state.count or after_state.count
            or (request_id and business_mode in {"issue_create", "issue_lookup"})
        )
        issue: IssueArtifact | None = None
        if is_issue:
            chosen_issue = issues[0] if issues else None
            record = facts.idempotency
            resource_key = _safe_identifier(record.resource_id) if record is not None else None
            response = (
                record.response_json if record is not None
                and isinstance(record.response_json, dict) else {}
            )
            issue = IssueArtifact(
                issue_key=(_safe_identifier(chosen_issue.issue_key) if chosen_issue
                           else resource_key),
                request_id=request_id,
                status=(
                    _safe_identifier(chosen_issue.status) if chosen_issue
                    else _safe_identifier(response.get("status"))
                ),
                draft_present=draft is not None,
                confirmation_state=(_safe_identifier(facts.confirmations[-1].status)
                                    if facts.confirmations else None),
                side_effect_count_before=before_state.count,
                side_effect_count_after=after_state.count,
                reconciliation_outcome=_safe_identifier(run_observation.reconciliation_outcome),
                metadata={
                    "candidate_issue_keys": [key for key in
                                             (_safe_identifier(v) for v in candidate_keys)
                                             if key is not None],
                    "candidate_status_by_issue": {
                        key: status
                        for _candidate, candidate_issue in facts.issue_candidates
                        if (key := _safe_identifier(candidate_issue.issue_key)) is not None
                        and (status := _safe_identifier(candidate_issue.status)) is not None
                    },
                    "candidate_ranks": [candidate.rank for candidate, _ in facts.issue_candidates],
                    "label_as_tool_data": bool(facts.issue_candidates),
                    "draft_status": _safe_identifier(draft.status) if draft else None,
                    "idempotency_status": (_safe_identifier(record.status)
                                           if record is not None else None),
                    "sandbox_event_types": [event.event_type for event in facts.sandbox_events],
                },
            )
        started = run.started_at if run is not None else None
        finished = run.finished_at if run is not None else None
        error = run_observation.error_category
        if error is not None and not _SAFE_ERROR.fullmatch(error):
            error = "UNCLASSIFIED_ERROR"
        trial = TrialArtifact(
            case_id=case.case_id, trial_no=run_observation.trial_no,
            classification=run_observation.classification,
            business_mode=business_mode,
            project_code=case.project_code, user_alias=case.user_alias,
            query=_text(case.question) or "[REDACTED]",
            query_sha256=hashlib.sha256(case.question.encode("utf-8")).hexdigest(),
            http_status=run_observation.http_status,
            run_id=str(run.id) if run is not None else None,
            thread_id=str(run.thread_id) if run is not None else None,
            status_transitions=tuple(statuses),
            event_types=tuple(event.event_type for event in events),
            started_at=_date(started), finished_at=_date(finished),
            latency_ms=(max(0.0, (finished - started).total_seconds() * 1000)
                        if started is not None and finished is not None else None),
            model_alias=_safe_identifier(run.model_alias) if run is not None else None,
            prompt_version=_safe_identifier(run.prompt_version) if run is not None else None,
            prompt_content_hash=(
                _safe_identifier(run.prompt_content_hash) if run is not None else None
            ),
            input_tokens=run.input_tokens if run is not None else None,
            output_tokens=run.output_tokens if run is not None else None,
            total_tokens=run.total_tokens if run is not None else None,
            retrieval_rounds=retrieval_rounds,
            final_retrieval_round=max(rounds) if rounds else None,
            governed_evidence=tuple(governed),
            answer=_text(facts.answer.answer_text) if facts.answer is not None else None,
            refusal_reason=(_text(facts.answer.refusal_reason)
                            if facts.answer is not None else None),
            citations=citations, issue=issue, error_category=error,
            metadata=metadata,
        )
        # Defense in depth: no secrets or unchecked arbitrary model/provider dicts.
        from project_agent.evaluation.artifacts import _to_jsonable

        _assert_secret_safe(_to_jsonable(trial))
        return trial
