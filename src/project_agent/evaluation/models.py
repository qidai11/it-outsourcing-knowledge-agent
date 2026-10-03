"""Immutable WS8 evaluation domain contracts.

The models in this module intentionally contain no runtime/provider behavior.  They
represent frozen benchmark inputs and raw evaluation outputs that later WS8 tasks
can collect and score deterministically.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

EMPTY_MAPPING: Mapping[str, Any] = MappingProxyType({})


class GoldScoringStatus(StrEnum):
    """Frozen Gold scoring eligibility."""

    SCORABLE = "SCORABLE"
    UNSCORABLE_GOLD = "UNSCORABLE_GOLD"
    UNSCORABLE_RUNTIME_SCOPE = "UNSCORABLE_RUNTIME_SCOPE"


class RunProtocol(StrEnum):
    """B7-frozen execution protocols."""

    SINGLE_RUN = "single_run"
    AUTHORIZATION_DENIAL = "authorization_denial"
    SETUP_THEN_RUN = "setup_then_run"
    WAITING_CONFIRMATION_RESUME = "waiting_confirmation_resume"
    SAME_REQUEST_REPLAY = "same_request_replay"
    RESPONSE_LOSS_RECONCILE = "response_loss_reconcile"
    UNSCORABLE_RUNTIME_SCOPE = "unscorable_runtime_scope"


class TrialClassification(StrEnum):
    """Every selected case must finish in exactly one classification."""

    SCORED = "SCORED"
    UNSCORABLE_GOLD = "UNSCORABLE_GOLD"
    UNSCORABLE_RUNTIME_SCOPE = "UNSCORABLE_RUNTIME_SCOPE"
    INFRA_FAILURE = "INFRA_FAILURE"
    RUNNER_FAILURE = "RUNNER_FAILURE"


class MetricStatus(StrEnum):
    """Allowed deterministic metric/report statuses."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNSCORABLE = "UNSCORABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    split: str
    priority: str
    project_code: str
    user_alias: str
    user_role: str
    question_type: str
    question: str
    expected_behavior: str
    expected_source_type: str
    expected_identifier: str | None
    expected_project_scope: str
    notes: str | None


@dataclass(frozen=True, slots=True)
class GoldExecution:
    business_mode: str
    run_protocol: RunProtocol
    project_code: str
    user_alias: str
    fixture_scenario: str | None = None
    setup_scenario: str | None = None
    fault_scenario: str | None = None
    request_overrides: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GoldScoring:
    status: GoldScoringStatus
    reason: str | None = None
    benchmark_finding_code: str | None = None


@dataclass(frozen=True, slots=True)
class GoldRecord:
    schema_version: str
    case_id: str
    dataset_version: str
    data_provenance: str
    execution: GoldExecution
    expected: Mapping[str, Any]
    metric_applicability: tuple[str, ...]
    scoring: GoldScoring
    authoring: Mapping[str, Any]
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    doc_code: str
    source_path: str
    sha256: str
    project_code: str
    document_category: str
    title: str
    version_no: int | None
    version_label: str | None
    authority_level: str
    lifecycle_status: str
    is_current: bool
    effective_from: str | None
    effective_to: str | None
    supersedes_doc_code: str | None
    identifier_targets: tuple[Mapping[str, Any], ...]
    provider_residue_mode: str
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EvaluationRunManifest:
    evaluation_run_id: str
    dataset_version: str
    data_provenance: str
    corpus_version: str
    gold_schema_version: str
    metric_definition_version: str
    git_commit: str
    dirty_worktree: bool
    selected_case_ids: tuple[str, ...]
    started_at: str | None = None
    python_version: str | None = None
    alembic_revision: str | None = None
    model_alias: str | None = None
    ragflow_expected_version: str | None = None
    ragflow_observed_version: str | None = None
    prompt_versions: tuple[str, ...] = ()
    prompt_hashes: tuple[str, ...] = ()
    runner_version: str | None = None
    dataset_sha256: str | None = None
    corpus_sha256: str | None = None
    gold_sha256: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: EMPTY_MAPPING)


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    evidence_id: str
    doc_code: str | None
    project_code: str | None
    rank: int | None = None
    document_version_id: str | None = None
    lifecycle_status: str | None = None
    is_current: bool | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: EMPTY_MAPPING)


@dataclass(frozen=True, slots=True)
class RetrievalRoundArtifact:
    round_no: int
    candidates: tuple[EvidenceArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class CitationArtifact:
    citation_id: str
    evidence_id: str
    claim_id: str | None = None
    doc_code: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: EMPTY_MAPPING)


@dataclass(frozen=True, slots=True)
class IssueArtifact:
    issue_key: str | None = None
    request_id: str | None = None
    status: str | None = None
    draft_present: bool | None = None
    confirmation_state: str | None = None
    side_effect_count_before: int | None = None
    side_effect_count_after: int | None = None
    reconciliation_outcome: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: EMPTY_MAPPING)


@dataclass(frozen=True, slots=True)
class TrialArtifact:
    case_id: str
    trial_no: int
    classification: TrialClassification
    business_mode: str
    project_code: str
    user_alias: str
    query: str
    query_sha256: str
    http_status: int | None = None
    run_id: str | None = None
    thread_id: str | None = None
    status_transitions: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    started_at: str | None = None
    finished_at: str | None = None
    latency_ms: float | None = None
    model_alias: str | None = None
    prompt_version: str | None = None
    prompt_content_hash: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    retrieval_rounds: tuple[RetrievalRoundArtifact, ...] = ()
    final_retrieval_round: int | None = None
    governed_evidence: tuple[EvidenceArtifact, ...] = ()
    answer: str | None = None
    refusal_reason: str | None = None
    citations: tuple[CitationArtifact, ...] = ()
    issue: IssueArtifact | None = None
    error_category: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: EMPTY_MAPPING)
