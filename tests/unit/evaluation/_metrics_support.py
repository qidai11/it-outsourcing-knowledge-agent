from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from project_agent.evaluation.dataset import load_evaluation_dataset
from project_agent.evaluation.models import (
    CitationArtifact,
    EvidenceArtifact,
    GoldExecution,
    GoldRecord,
    GoldScoring,
    GoldScoringStatus,
    IssueArtifact,
    RetrievalRoundArtifact,
    RunProtocol,
    TrialArtifact,
    TrialClassification,
)

DATASET = load_evaluation_dataset(Path("evaluation/datasets/v0"))


def make_gold(
    case_id: str = "Q900",
    *,
    applicable: tuple[str, ...] = (),
    expected: Mapping[str, object] | None = None,
    scoring: GoldScoringStatus = GoldScoringStatus.SCORABLE,
    project_code: str = "PRJ-ALPHA",
) -> GoldRecord:
    default_expected: dict[str, object] = {
        "behavior_class": "answer_with_citation",
        "expected_http_statuses": [],
        "run_creation_expected": True,
        "acceptable_run_statuses": ["SUCCEEDED"],
        "identifier_targets": [],
        "required_evidence_groups": [],
        "forbidden_doc_codes": [],
        "current_doc_codes": [],
        "answer": {
            "refusal_expected": False,
            "required_tokens": [],
            "any_of_token_groups": [],
            "forbidden_tokens": [],
        },
        "citations": {"mode": "not_applicable", "claim_groups": []},
        "tool": {
            "live_state_required": False,
            "required_issue_groups": [],
            "forbidden_issue_keys": [],
            "required_status_by_issue": {},
            "label_as_tool_data": False,
        },
        "issue": {
            "draft_expected": None,
            "confirmation_expected": None,
            "side_effects_before_confirmation": None,
            "side_effects_after_confirmation": None,
            "max_logical_side_effects": None,
            "expected_creation_outcomes": [],
        },
        "safety_assertions": [],
    }
    if expected:
        default_expected.update(expected)
    return GoldRecord(
        schema_version="gold-v1",
        case_id=case_id,
        dataset_version="v0",
        data_provenance="synthetic",
        execution=GoldExecution(
            business_mode="qa",
            run_protocol=RunProtocol.SINGLE_RUN,
            project_code=project_code,
            user_alias="u",
        ),
        expected=default_expected,
        metric_applicability=applicable,
        scoring=GoldScoring(status=scoring),
        authoring={},
        raw={},
    )


def ev(
    doc_code: str,
    *,
    rank: int = 1,
    project_code: str = "PRJ-ALPHA",
    evidence_id: str | None = None,
    lifecycle_status: str = "PUBLISHED",
    is_current: bool = True,
    metadata: Mapping[str, object] | None = None,
) -> EvidenceArtifact:
    return EvidenceArtifact(
        evidence_id=evidence_id or f"e-{doc_code}-{rank}",
        doc_code=doc_code,
        project_code=project_code,
        rank=rank,
        lifecycle_status=lifecycle_status,
        is_current=is_current,
        metadata=metadata or {},
    )


def trial(
    case_id: str = "Q900",
    *,
    candidates: tuple[EvidenceArtifact, ...] = (),
    first_candidates: tuple[EvidenceArtifact, ...] | None = None,
    governed: tuple[EvidenceArtifact, ...] = (),
    citations: tuple[CitationArtifact, ...] = (),
    issue: IssueArtifact | None = None,
    answer: str | None = "answer",
    refusal_reason: str | None = None,
    status: tuple[str, ...] = ("SUCCEEDED",),
    http_status: int | None = 200,
    run_id: str | None = "run-1",
    project_code: str = "PRJ-ALPHA",
    classification: TrialClassification = TrialClassification.SCORED,
    metadata: Mapping[str, object] | None = None,
    latency_ms: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
) -> TrialArtifact:
    rounds = []
    if first_candidates is not None:
        rounds.append(RetrievalRoundArtifact(round_no=1, candidates=first_candidates))
        rounds.append(RetrievalRoundArtifact(round_no=2, candidates=candidates))
    elif candidates:
        rounds.append(RetrievalRoundArtifact(round_no=1, candidates=candidates))
    return TrialArtifact(
        case_id=case_id,
        trial_no=1,
        classification=classification,
        business_mode="qa",
        project_code=project_code,
        user_alias="u",
        query="q",
        query_sha256="0" * 64,
        http_status=http_status,
        run_id=run_id,
        status_transitions=status,
        retrieval_rounds=tuple(rounds),
        final_retrieval_round=(rounds[-1].round_no if rounds else None),
        governed_evidence=governed,
        answer=answer,
        refusal_reason=refusal_reason,
        citations=citations,
        issue=issue,
        metadata=metadata or {},
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def citation(evidence: EvidenceArtifact, *, citation_id: str = "c1") -> CitationArtifact:
    return CitationArtifact(
        citation_id=citation_id,
        evidence_id=evidence.evidence_id,
        doc_code=evidence.doc_code,
    )
