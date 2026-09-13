from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from project_agent.domain.evidence import FrozenEvidenceBundle, GroundedAnswerDraft
from project_agent.domain.enums import DocumentLifecycleStatus


@dataclass(frozen=True, slots=True)
class CitationValidationResult:
    valid: bool
    coverage: float
    errors: tuple[str, ...]
    used_evidence_ids: tuple[str, ...]


class CitationGuard:
    def validate(
        self,
        draft: GroundedAnswerDraft,
        *,
        bundle: FrozenEvidenceBundle,
        project_id: UUID,
    ) -> CitationValidationResult:
        labels = [item.label for item in bundle.evidence]
        evidence_by_label = {item.label: item for item in bundle.evidence}
        errors: list[str] = []
        for label in labels:
            if labels.count(label) > 1:
                errors.append(f"DUPLICATE_EVIDENCE_LABEL:{label}")
        used: list[str] = []
        covered_claims = 0

        for index, claim in enumerate(draft.claims, start=1):
            if not claim.evidence_ids:
                errors.append(f"UNCITED_CLAIM:{index}")
                continue
            claim_valid = True
            for label in claim.evidence_ids:
                item = evidence_by_label.get(label)
                if item is None:
                    errors.append(f"UNKNOWN_EVIDENCE_ID:{label}")
                    claim_valid = False
                    continue
                if item.project_id != project_id:
                    errors.append(f"CROSS_PROJECT_EVIDENCE:{label}")
                    claim_valid = False
                if item.lifecycle_status is not DocumentLifecycleStatus.PUBLISHED or not item.is_current:
                    errors.append(f"NON_CURRENT_EVIDENCE:{label}")
                    claim_valid = False
                if label not in used:
                    used.append(label)
            if claim_valid:
                covered_claims += 1

        disclosure = draft.conflict_disclosure
        if disclosure is not None:
            for label in disclosure.evidence_ids:
                item = evidence_by_label.get(label)
                if item is None:
                    errors.append(f"UNKNOWN_EVIDENCE_ID:{label}")
                elif item.project_id != project_id:
                    errors.append(f"CROSS_PROJECT_EVIDENCE:{label}")
                if label not in used and item is not None:
                    used.append(label)

        disclosure_ids = set(disclosure.evidence_ids) if disclosure is not None else set()
        for key, required_ids in bundle.unresolved_conflicts.items():
            if disclosure is None or not set(required_ids).issubset(disclosure_ids):
                errors.append(f"MISSING_CONFLICT_DISCLOSURE:{key}")

        total = len(draft.claims)
        coverage = covered_claims / total if total else 0.0
        if total == 0:
            errors.append("NO_FACTUAL_CLAIMS")
        return CitationValidationResult(
            valid=not errors and coverage == 1.0,
            coverage=coverage,
            errors=tuple(dict.fromkeys(errors)),
            used_evidence_ids=tuple(used),
        )
