"""Pure deterministic WS8 acceptance metrics v1.

All calculations operate on persisted :class:`TrialArtifact` values and frozen
benchmark metadata.  No function in this module owns an application/provider/database
client, making saved-artifact replay deterministic by construction.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from project_agent.evaluation.models import (
    CorpusDocument,
    EvaluationCase,
    EvidenceArtifact,
    GoldRecord,
    GoldScoringStatus,
    MetricStatus,
    RunProtocol,
    TrialArtifact,
    TrialClassification,
)
from project_agent.evaluation.scoring import CaseBehaviorResult, score_case_behavior

METRIC_DEFINITION_VERSION = "v1"
FROZEN_METRIC_ORDER = (
    "exact_identifier_hit_at_10",
    "evidence_recall_at_10",
    "current_version_hit_rate",
    "citation_id_validity",
    "no_answer_refusal_accuracy",
    "cross_project_evidence",
    "unconfirmed_issue_creation",
    "duplicate_issue_side_effects",
    "critical_regression",
)
_TARGETS: Mapping[str, str] = {
    "exact_identifier_hit_at_10": ">= 0.95",
    "evidence_recall_at_10": ">= 0.90",
    "current_version_hit_rate": ">= 0.95",
    "citation_id_validity": "== 1.00",
    "no_answer_refusal_accuracy": ">= 0.90",
    "cross_project_evidence": "== 0",
    "unconfirmed_issue_creation": "== 0",
    "duplicate_issue_side_effects": "== 0",
    "critical_regression": "== 1.00",
}


@dataclass(frozen=True, slots=True)
class MetricResult:
    metric_id: str
    target: str
    measured: float | int | None
    numerator: float | int | None
    denominator: int | None
    status: MetricStatus
    case_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    metric_definition_version: str
    coverage: Mapping[str, int]
    acceptance_metrics: tuple[MetricResult, ...]
    diagnostic_metrics: Mapping[str, Any]
    case_behavior_results: tuple[CaseBehaviorResult, ...]


def _ordered_trials(trials: Sequence[TrialArtifact]) -> tuple[TrialArtifact, ...]:
    ordered = tuple(sorted(trials, key=lambda item: (item.case_id, item.trial_no)))
    seen: set[str] = set()
    for item in ordered:
        if item.case_id in seen:
            raise ValueError(f"multiple trial artifacts for case {item.case_id}")
        seen.add(item.case_id)
    return ordered


def _final_candidates(trial: TrialArtifact) -> tuple[EvidenceArtifact, ...]:
    if not trial.retrieval_rounds:
        return ()
    target = trial.final_retrieval_round
    if target is None:
        target = max(item.round_no for item in trial.retrieval_rounds)
    for round_artifact in trial.retrieval_rounds:
        if round_artifact.round_no == target:
            return round_artifact.candidates
    return ()


def _first_candidates(trial: TrialArtifact) -> tuple[EvidenceArtifact, ...]:
    if not trial.retrieval_rounds:
        return ()
    first = min(trial.retrieval_rounds, key=lambda item: item.round_no)
    return first.candidates


def _top10_doc_codes(
    candidates: Sequence[EvidenceArtifact],
    trial: TrialArtifact,
    documents_by_code: Mapping[str, CorpusDocument],
) -> set[str]:
    result: set[str] = set()
    for item in candidates:
        if item.rank is None or item.rank < 1 or item.rank > 10 or item.doc_code is None:
            continue
        if item.project_code not in (None, trial.project_code):
            continue
        document = documents_by_code.get(item.doc_code)
        if document is not None and document.project_code != trial.project_code:
            continue
        result.add(item.doc_code)
    return result


def _applicable(
    metric_id: str,
    trials: Sequence[TrialArtifact],
    gold_by_case: Mapping[str, GoldRecord],
) -> tuple[tuple[TrialArtifact, GoldRecord], ...]:
    pairs: list[tuple[TrialArtifact, GoldRecord]] = []
    for trial in trials:
        gold = gold_by_case.get(trial.case_id)
        if gold is None:
            raise ValueError(f"missing Gold for trial {trial.case_id}")
        if metric_id in gold.metric_applicability:
            pairs.append((trial, gold))
    return tuple(pairs)


def _scorable_pairs(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
) -> tuple[tuple[TrialArtifact, GoldRecord], ...]:
    return tuple(
        pair
        for pair in pairs
        if pair[1].scoring.status is GoldScoringStatus.SCORABLE
        and pair[0].classification is TrialClassification.SCORED
    )


def _base_status(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]], denominator: int | None
) -> MetricStatus | None:
    if not pairs:
        return MetricStatus.NOT_APPLICABLE
    if not denominator:
        return MetricStatus.UNSCORABLE
    return None


def _rate_status(measured: float | None, threshold: float, *, exact: bool = False) -> MetricStatus:
    if measured is None:
        return MetricStatus.UNSCORABLE
    passed = measured == threshold if exact else measured >= threshold
    return MetricStatus.PASS if passed else MetricStatus.FAIL


def _count_status(measured: int | None) -> MetricStatus:
    if measured is None:
        return MetricStatus.UNSCORABLE
    return MetricStatus.PASS if measured == 0 else MetricStatus.FAIL


def _notes_for_unscorable(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
) -> tuple[str, ...]:
    notes: list[str] = []
    for trial, gold in pairs:
        if gold.scoring.status is not GoldScoringStatus.SCORABLE:
            notes.append(f"{gold.case_id}: {gold.scoring.status.value}")
        elif trial.classification is not TrialClassification.SCORED:
            notes.append(f"{trial.case_id}: {trial.classification.value}")
    return tuple(notes)


def _identifier_result(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
    documents_by_code: Mapping[str, CorpusDocument],
    *,
    candidate_getter: Callable[[TrialArtifact], tuple[EvidenceArtifact, ...]] = _final_candidates,
) -> MetricResult:
    metric_id = "exact_identifier_hit_at_10"
    scorable = _scorable_pairs(pairs)
    hits = 0
    total = 0
    case_ids: list[str] = []
    for trial, gold in scorable:
        targets = gold.expected.get("identifier_targets", ())
        if not targets:
            continue
        docs = _top10_doc_codes(candidate_getter(trial), trial, documents_by_code)
        case_ids.append(trial.case_id)
        for target in targets:
            if not isinstance(target, Mapping):
                continue
            acceptable = {str(item) for item in target.get("acceptable_doc_codes", ())}
            total += 1
            if not docs.isdisjoint(acceptable):
                hits += 1
    measured = hits / total if total else None
    base = _base_status(pairs, total)
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=measured,
        numerator=hits if total else None,
        denominator=total,
        status=base or _rate_status(measured, 0.95),
        case_ids=tuple(sorted(case_ids)),
        notes=_notes_for_unscorable(pairs),
    )


def _evidence_result(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
    documents_by_code: Mapping[str, CorpusDocument],
    *,
    candidate_getter: Callable[[TrialArtifact], tuple[EvidenceArtifact, ...]] = _final_candidates,
) -> MetricResult:
    metric_id = "evidence_recall_at_10"
    recalls: list[float] = []
    case_ids: list[str] = []
    for trial, gold in _scorable_pairs(pairs):
        groups = gold.expected.get("required_evidence_groups", ())
        if not groups:
            continue
        docs = _top10_doc_codes(candidate_getter(trial), trial, documents_by_code)
        hits = 0
        count = 0
        for group in groups:
            acceptable = {str(item) for item in group}
            if not acceptable:
                continue
            count += 1
            if not docs.isdisjoint(acceptable):
                hits += 1
        if count:
            recalls.append(hits / count)
            case_ids.append(trial.case_id)
    denominator = len(recalls)
    numerator = sum(recalls) if recalls else None
    measured = (float(numerator) / denominator) if numerator is not None and denominator else None
    base = _base_status(pairs, denominator)
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=measured,
        numerator=numerator,
        denominator=denominator,
        status=base or _rate_status(measured, 0.90),
        case_ids=tuple(sorted(case_ids)),
        notes=_notes_for_unscorable(pairs),
    )


def _current_version_result(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
) -> MetricResult:
    metric_id = "current_version_hit_rate"
    passed = 0
    scorable_cases = 0
    case_ids: list[str] = []
    for trial, gold in _scorable_pairs(pairs):
        current = {str(item) for item in gold.expected.get("current_doc_codes", ())}
        if not current:
            continue
        forbidden = {str(item) for item in gold.expected.get("forbidden_doc_codes", ())}
        governed = trial.governed_evidence
        expected_current_present = any(
            item.doc_code in current
            and item.lifecycle_status == "PUBLISHED"
            and item.is_current is True
            for item in governed
        )
        forbidden_present = any(item.doc_code in forbidden for item in governed)
        scorable_cases += 1
        case_ids.append(trial.case_id)
        if expected_current_present and not forbidden_present:
            passed += 1
    measured = passed / scorable_cases if scorable_cases else None
    base = _base_status(pairs, scorable_cases)
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=measured,
        numerator=passed if scorable_cases else None,
        denominator=scorable_cases,
        status=base or _rate_status(measured, 0.95),
        case_ids=tuple(sorted(case_ids)),
        notes=_notes_for_unscorable(pairs),
    )


def _citation_valid(
    trial: TrialArtifact,
    evidence: EvidenceArtifact | None,
    documents_by_code: Mapping[str, CorpusDocument],
) -> bool:
    if evidence is None:
        return False
    run_id = evidence.metadata.get("run_id")
    if run_id is not None and str(run_id) != str(trial.run_id):
        return False
    if evidence.project_code not in (None, trial.project_code):
        return False
    doc_code = evidence.doc_code
    document = documents_by_code.get(doc_code) if doc_code is not None else None
    if document is not None and document.project_code != trial.project_code:
        return False
    return evidence.lifecycle_status == "PUBLISHED" and evidence.is_current is True


def _citation_result(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
    documents_by_code: Mapping[str, CorpusDocument],
) -> MetricResult:
    metric_id = "citation_id_validity"
    valid = 0
    denominator = 0
    case_ids: list[str] = []
    for trial, gold in _scorable_pairs(pairs):
        citation_config = gold.expected.get("citations", {})
        mode = (
            str(citation_config.get("mode", "not_applicable"))
            if isinstance(citation_config, Mapping)
            else "not_applicable"
        )
        answered = bool((trial.answer or "").strip()) and not _safe_refusal(trial)
        citations_required = mode == "required" or (mode == "required_if_answered" and answered)
        governed = {item.evidence_id: item for item in trial.governed_evidence}
        case_denominator = len(trial.citations)
        if citations_required and not trial.citations:
            # Required zero-citation answers get an explicit failing denominator unit.
            case_denominator = 1
        if case_denominator == 0:
            continue
        denominator += case_denominator
        case_ids.append(trial.case_id)
        for citation in trial.citations:
            if _citation_valid(trial, governed.get(citation.evidence_id), documents_by_code):
                valid += 1
    measured = valid / denominator if denominator else None
    base = _base_status(pairs, denominator)
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=measured,
        numerator=valid if denominator else None,
        denominator=denominator,
        status=base or _rate_status(measured, 1.0, exact=True),
        case_ids=tuple(sorted(case_ids)),
        notes=_notes_for_unscorable(pairs),
    )


def _safe_refusal(trial: TrialArtifact) -> bool:
    if trial.refusal_reason:
        return True
    if trial.status_transitions and trial.status_transitions[-1] == "REFUSED":
        return True
    return not (trial.answer or "").strip() and not trial.governed_evidence


def _refusal_result(pairs: Sequence[tuple[TrialArtifact, GoldRecord]]) -> MetricResult:
    metric_id = "no_answer_refusal_accuracy"
    passed = 0
    denominator = 0
    case_ids: list[str] = []
    for trial, gold in _scorable_pairs(pairs):
        if gold.execution.run_protocol is RunProtocol.AUTHORIZATION_DENIAL:
            continue
        answer = gold.expected.get("answer", {})
        if not isinstance(answer, Mapping) or answer.get("refusal_expected") is not True:
            continue
        denominator += 1
        case_ids.append(trial.case_id)
        if _safe_refusal(trial):
            passed += 1
    measured = passed / denominator if denominator else None
    base = _base_status(pairs, denominator)
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=measured,
        numerator=passed if denominator else None,
        denominator=denominator,
        status=base or _rate_status(measured, 0.90),
        case_ids=tuple(sorted(case_ids)),
        notes=_notes_for_unscorable(pairs),
    )


def _evidence_project_outside(
    evidence: EvidenceArtifact,
    trial: TrialArtifact,
    documents_by_code: Mapping[str, CorpusDocument],
) -> bool:
    if evidence.project_code not in (None, trial.project_code):
        return True
    if evidence.doc_code is not None and evidence.doc_code in documents_by_code:
        return documents_by_code[evidence.doc_code].project_code != trial.project_code
    return False


def _cross_project_result(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
    documents_by_code: Mapping[str, CorpusDocument],
) -> MetricResult:
    metric_id = "cross_project_evidence"
    violations = 0
    scorable = _scorable_pairs(pairs)
    for trial, _gold in scorable:
        evidence_by_id: dict[str, EvidenceArtifact] = {}
        for round_artifact in trial.retrieval_rounds:
            for item in round_artifact.candidates:
                evidence_by_id[item.evidence_id] = item
                violations += int(_evidence_project_outside(item, trial, documents_by_code))
        for item in trial.governed_evidence:
            evidence_by_id[item.evidence_id] = item
            violations += int(_evidence_project_outside(item, trial, documents_by_code))
        # A cross-project citation is an additional persisted scope violation.  If it
        # references an already-counted cross-project snapshot, count the citation too:
        # the Design explicitly names candidate, governed Evidence, *and* citation.
        for citation in trial.citations:
            evidence = evidence_by_id.get(citation.evidence_id)
            outside = evidence is not None and _evidence_project_outside(
                evidence, trial, documents_by_code
            )
            if not outside and citation.doc_code is not None:
                doc = documents_by_code.get(citation.doc_code)
                outside = doc is not None and doc.project_code != trial.project_code
            violations += int(outside)
    denominator = len(scorable)
    base = _base_status(pairs, denominator)
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=violations if denominator else None,
        numerator=violations if denominator else None,
        denominator=denominator,
        status=base or _count_status(violations),
        case_ids=tuple(sorted(trial.case_id for trial, _gold in scorable)),
        notes=_notes_for_unscorable(pairs),
    )


def _unconfirmed_issue_result(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
) -> MetricResult:
    metric_id = "unconfirmed_issue_creation"
    violations = 0
    case_ids: list[str] = []
    missing: list[str] = []
    for trial, _gold in _scorable_pairs(pairs):
        case_ids.append(trial.case_id)
        if trial.issue is None or trial.issue.side_effect_count_before is None:
            missing.append(trial.case_id)
            continue
        violations += max(0, trial.issue.side_effect_count_before)
    denominator = len(case_ids) - len(missing)
    notes = list(_notes_for_unscorable(pairs))
    notes.extend(f"{case_id}: missing issue side-effect snapshot" for case_id in missing)
    base = _base_status(pairs, denominator)
    status = base or _count_status(violations)
    if missing:
        status = MetricStatus.UNSCORABLE
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=violations if denominator else None,
        numerator=violations if denominator else None,
        denominator=denominator,
        status=status,
        case_ids=tuple(sorted(case_id for case_id in case_ids if case_id not in missing)),
        notes=tuple(notes),
    )


def _duplicate_issue_result(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
) -> MetricResult:
    metric_id = "duplicate_issue_side_effects"
    violations = 0
    case_ids: list[str] = []
    missing: list[str] = []
    for trial, _gold in _scorable_pairs(pairs):
        case_ids.append(trial.case_id)
        if trial.issue is None or trial.issue.side_effect_count_after is None:
            missing.append(trial.case_id)
            continue
        violations += max(0, trial.issue.side_effect_count_after - 1)
    denominator = len(case_ids) - len(missing)
    notes = list(_notes_for_unscorable(pairs))
    notes.extend(f"{case_id}: missing issue side-effect snapshot" for case_id in missing)
    base = _base_status(pairs, denominator)
    status = base or _count_status(violations)
    if missing:
        status = MetricStatus.UNSCORABLE
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=violations if denominator else None,
        numerator=violations if denominator else None,
        denominator=denominator,
        status=status,
        case_ids=tuple(sorted(case_id for case_id in case_ids if case_id not in missing)),
        notes=tuple(notes),
    )


def _critical_result(
    pairs: Sequence[tuple[TrialArtifact, GoldRecord]],
    behavior_by_case: Mapping[str, CaseBehaviorResult],
) -> MetricResult:
    metric_id = "critical_regression"
    passed = 0
    denominator = 0
    case_ids: list[str] = []
    unscorable: list[str] = []
    for trial, gold in pairs:
        if gold.scoring.status is not GoldScoringStatus.SCORABLE:
            unscorable.append(gold.case_id)
            continue
        result = behavior_by_case[trial.case_id]
        if result.status is MetricStatus.UNSCORABLE:
            unscorable.append(trial.case_id)
            continue
        denominator += 1
        case_ids.append(trial.case_id)
        if result.status is MetricStatus.PASS:
            passed += 1
    measured = passed / denominator if denominator else None
    base = _base_status(pairs, denominator)
    status = base or _rate_status(measured, 1.0, exact=True)
    notes = list(_notes_for_unscorable(pairs))
    if unscorable:
        status = MetricStatus.UNSCORABLE
        notes.append("unscorable P0 prevents full proof: " + ", ".join(sorted(unscorable)))
    return MetricResult(
        metric_id=metric_id,
        target=_TARGETS[metric_id],
        measured=measured,
        numerator=passed if denominator else None,
        denominator=denominator,
        status=status,
        case_ids=tuple(sorted(case_ids)),
        notes=tuple(dict.fromkeys(notes)),
    )


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _rate_map(
    behavior_results: Sequence[CaseBehaviorResult],
    key_by_case: Mapping[str, str],
) -> Mapping[str, Mapping[str, float | int | None]]:
    totals: Counter[str] = Counter()
    passes: Counter[str] = Counter()
    for result in behavior_results:
        if result.status not in {MetricStatus.PASS, MetricStatus.FAIL}:
            continue
        key = key_by_case.get(result.case_id)
        if key is None:
            continue
        totals[key] += 1
        passes[key] += int(result.status is MetricStatus.PASS)
    return {
        key: {
            "passed": passes[key],
            "total": totals[key],
            "rate": passes[key] / totals[key] if totals[key] else None,
        }
        for key in sorted(totals)
    }


def _diagnostics(
    trials: Sequence[TrialArtifact],
    gold_by_case: Mapping[str, GoldRecord],
    documents_by_code: Mapping[str, CorpusDocument],
    behavior_results: Sequence[CaseBehaviorResult],
    cases_by_id: Mapping[str, EvaluationCase],
    *,
    cost_per_input_token: float | None,
    cost_per_output_token: float | None,
) -> Mapping[str, Any]:
    counts = Counter(item.classification.value for item in trials)
    scorable = sum(
        item.classification is TrialClassification.SCORED
        and gold_by_case[item.case_id].scoring.status is GoldScoringStatus.SCORABLE
        for item in trials
    )
    unscorable = sum(
        item.classification
        in {TrialClassification.UNSCORABLE_GOLD, TrialClassification.UNSCORABLE_RUNTIME_SCOPE}
        or gold_by_case[item.case_id].scoring.status is not GoldScoringStatus.SCORABLE
        for item in trials
    )

    identifier_pairs = _applicable("exact_identifier_hit_at_10", trials, gold_by_case)
    evidence_pairs = _applicable("evidence_recall_at_10", trials, gold_by_case)
    first_identifier = _identifier_result(
        identifier_pairs, documents_by_code, candidate_getter=_first_candidates
    )
    final_identifier = _identifier_result(identifier_pairs, documents_by_code)
    first_evidence = _evidence_result(
        evidence_pairs, documents_by_code, candidate_getter=_first_candidates
    )
    final_evidence = _evidence_result(evidence_pairs, documents_by_code)

    second_round_count = sum(len(item.retrieval_rounds) >= 2 for item in trials)
    rounds = Counter(len(item.retrieval_rounds) for item in trials)
    guards: Counter[str] = Counter()
    guard_coverages: list[float] = []
    for trial in trials:
        raw_guard = trial.metadata.get("citation_guard")
        if not isinstance(raw_guard, Mapping):
            continue
        coverage = raw_guard.get("coverage")
        if isinstance(coverage, (int, float)) and not isinstance(coverage, bool):
            guard_coverages.append(float(coverage))
        valid = raw_guard.get("valid")
        coverage_ok = raw_guard.get("coverage_ok")
        if valid is True and coverage_ok is not False:
            guards["pass"] += 1
        elif trial.refusal_reason or (
            trial.status_transitions and trial.status_transitions[-1] == "REFUSED"
        ):
            guards["refusal"] += 1
        else:
            guards["revision"] += 1

    latencies = [float(item.latency_ms) for item in trials if item.latency_ms is not None]
    total_tokens = [item.total_tokens for item in trials if item.total_tokens is not None]
    input_total = sum(item.input_tokens or 0 for item in trials)
    output_total = sum(item.output_tokens or 0 for item in trials)
    token_total = sum(total_tokens)
    issue_candidate_counts = [
        len(item.issue.metadata.get("candidate_issue_keys", ()))
        for item in trials
        if item.issue is not None
        and isinstance(item.issue.metadata.get("candidate_issue_keys", ()), (list, tuple))
    ]
    issue_candidate_ranks: list[int] = []
    issue_best_ranks: list[int] = []
    for trial in trials:
        if trial.issue is None:
            continue
        raw_ranks = trial.issue.metadata.get("candidate_ranks", ())
        if not isinstance(raw_ranks, (list, tuple)):
            continue
        ranks = [
            int(value)
            for value in raw_ranks
            if isinstance(value, int) and not isinstance(value, bool) and value >= 1
        ]
        issue_candidate_ranks.extend(ranks)
        if ranks:
            issue_best_ranks.append(min(ranks))
    issue_rank_distribution = Counter(issue_candidate_ranks)
    guard_denominator = sum(guards.values())

    project_keys = {item.case_id: item.project_code for item in trials}
    split_keys = {case_id: case.split for case_id, case in cases_by_id.items()}
    type_keys = {case_id: case.question_type for case_id, case in cases_by_id.items()}

    diagnostics: dict[str, Any] = {
        "coverage": {
            "selected": len(trials),
            "scored": counts[TrialClassification.SCORED.value],
            "scorable": scorable,
            "unscorable": unscorable,
            "infra_failure": counts[TrialClassification.INFRA_FAILURE.value],
            "runner_failure": counts[TrialClassification.RUNNER_FAILURE.value],
        },
        "retrieval": {
            "first_round_identifier_hit_at_10": first_identifier.measured,
            "final_round_identifier_hit_at_10": final_identifier.measured,
            "first_round_evidence_recall_at_10": first_evidence.measured,
            "final_round_evidence_recall_at_10": final_evidence.measured,
        },
        "second_round_usage": {
            "count": second_round_count,
            "denominator": len(trials),
            "rate": second_round_count / len(trials) if trials else None,
        },
        "citation_guard": {
            "denominator": guard_denominator,
            "pass": guards["pass"],
            "revision": guards["revision"],
            "refusal": guards["refusal"],
            "pass_rate": guards["pass"] / guard_denominator if guard_denominator else None,
            "revision_rate": (
                guards["revision"] / guard_denominator if guard_denominator else None
            ),
            "refusal_rate": guards["refusal"] / guard_denominator if guard_denominator else None,
            "claim_coverage_mean": statistics.fmean(guard_coverages) if guard_coverages else None,
        },
        "latency_ms": {
            "mean": statistics.fmean(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "p95": _percentile(latencies, 0.95),
        },
        "tokens": {
            "input_total": input_total,
            "output_total": output_total,
            "total": token_total,
            "mean": statistics.fmean(total_tokens) if total_tokens else None,
            "p95": _percentile([float(value) for value in total_tokens], 0.95),
        },
        "retrieval_round_distribution": {str(key): rounds[key] for key in sorted(rounds)},
        "issue_candidates": {
            "cases_with_candidate_data": len(issue_candidate_counts),
            "mean_candidate_count": (
                statistics.fmean(issue_candidate_counts) if issue_candidate_counts else None
            ),
            "rank_distribution": {
                str(key): issue_rank_distribution[key] for key in sorted(issue_rank_distribution)
            },
            "mean_best_rank": (statistics.fmean(issue_best_ranks) if issue_best_ranks else None),
        },
        "pass_rate_by_question_type": _rate_map(behavior_results, type_keys),
        "pass_rate_by_split": _rate_map(behavior_results, split_keys),
        "pass_rate_by_project": _rate_map(behavior_results, project_keys),
    }
    if cost_per_input_token is not None or cost_per_output_token is not None:
        diagnostics["estimated_cost"] = input_total * (
            cost_per_input_token or 0.0
        ) + output_total * (cost_per_output_token or 0.0)
    else:
        diagnostics["estimated_cost"] = None
    return diagnostics


def calculate_metrics(
    trials: Sequence[TrialArtifact],
    gold_by_case: Mapping[str, GoldRecord],
    documents_by_code: Mapping[str, CorpusDocument],
    *,
    metric_definition_version: str = METRIC_DEFINITION_VERSION,
    cases_by_id: Mapping[str, EvaluationCase] | None = None,
    cost_per_input_token: float | None = None,
    cost_per_output_token: float | None = None,
) -> EvaluationMetrics:
    """Score saved artifacts using the frozen V1 formulas.

    Only metrics applicable to at least one selected case are returned.  A full B7
    run therefore contains all nine metrics in :data:`FROZEN_METRIC_ORDER`.
    """

    if metric_definition_version != METRIC_DEFINITION_VERSION:
        raise ValueError(f"unsupported metric_definition_version: {metric_definition_version}")
    ordered = _ordered_trials(trials)
    case_metadata = cases_by_id or {}
    behavior_results = tuple(
        score_case_behavior(item, gold_by_case[item.case_id], documents_by_code) for item in ordered
    )
    behavior_by_case = {item.case_id: item for item in behavior_results}

    calculators: Mapping[
        str,
        Callable[[Sequence[tuple[TrialArtifact, GoldRecord]]], MetricResult],
    ] = {
        "exact_identifier_hit_at_10": lambda pairs: _identifier_result(pairs, documents_by_code),
        "evidence_recall_at_10": lambda pairs: _evidence_result(pairs, documents_by_code),
        "current_version_hit_rate": _current_version_result,
        "citation_id_validity": lambda pairs: _citation_result(pairs, documents_by_code),
        "no_answer_refusal_accuracy": _refusal_result,
        "cross_project_evidence": lambda pairs: _cross_project_result(pairs, documents_by_code),
        "unconfirmed_issue_creation": _unconfirmed_issue_result,
        "duplicate_issue_side_effects": _duplicate_issue_result,
        "critical_regression": lambda pairs: _critical_result(pairs, behavior_by_case),
    }

    results: list[MetricResult] = []
    for metric_id in FROZEN_METRIC_ORDER:
        pairs = _applicable(metric_id, ordered, gold_by_case)
        if pairs:
            results.append(calculators[metric_id](pairs))

    counts = Counter(item.classification.value for item in ordered)
    coverage = {
        "selected": len(ordered),
        "scored": counts[TrialClassification.SCORED.value],
        "unscorable_gold": counts[TrialClassification.UNSCORABLE_GOLD.value],
        "unscorable_runtime_scope": counts[TrialClassification.UNSCORABLE_RUNTIME_SCOPE.value],
        "infra_failure": counts[TrialClassification.INFRA_FAILURE.value],
        "runner_failure": counts[TrialClassification.RUNNER_FAILURE.value],
    }
    diagnostics = _diagnostics(
        ordered,
        gold_by_case,
        documents_by_code,
        behavior_results,
        case_metadata,
        cost_per_input_token=cost_per_input_token,
        cost_per_output_token=cost_per_output_token,
    )
    return EvaluationMetrics(
        metric_definition_version=metric_definition_version,
        coverage=coverage,
        acceptance_metrics=tuple(results),
        diagnostic_metrics=diagnostics,
        case_behavior_results=behavior_results,
    )
