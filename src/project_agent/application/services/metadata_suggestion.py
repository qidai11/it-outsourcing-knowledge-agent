from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from project_agent.domain.metadata import MetadataSuggestion


@dataclass(frozen=True, slots=True)
class ExistingDocumentVersion:
    version_id: UUID
    document_category: str
    version_label: str
    lifecycle_status: str


@dataclass(frozen=True, slots=True)
class MetadataSuggestionInput:
    project_id: UUID
    project_code: str
    filename: str
    preview_text: str
    existing_versions: tuple[ExistingDocumentVersion, ...] = ()


_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "requirement_baseline",
        ("requirement", "requirements", "需求", "需求规格"),
        "requirement_baseline",
    ),
    ("api_specification", ("api", "接口", "openapi"), "approved_design"),
    ("database_design", ("database", "db", "数据库", "数据字典"), "approved_design"),
    ("approved_test_spec", ("test", "uat", "验收", "测试"), "approved_test_spec"),
    (
        "release_runbook",
        ("release", "deploy", "deployment", "上线", "部署"),
        "release_runbook",
    ),
    (
        "approved_meeting_minutes",
        ("meeting", "minutes", "会议纪要", "会议"),
        "approved_meeting_minutes",
    ),
    ("issue_record", ("issue", "bug", "故障", "问题记录"), "issue_record"),
)
_VERSION_RE = re.compile(
    r"(?i)(?:\bv(?:ersion)?\s*|版本\s*)?(\d+(?:\.\d+){1,3}(?:[-_][a-z0-9]+)?)"
)


class MetadataSuggestionService:
    """Deterministic metadata prefill baseline.

    The service deliberately returns suggestions only. It has no lifecycle field,
    no confirmer, and no capability to publish a document.
    """

    def __init__(self, *, confidence_threshold: float = 0.75) -> None:
        self._threshold = confidence_threshold

    def suggest(self, request: MetadataSuggestionInput) -> MetadataSuggestion:
        filename_lower = request.filename.casefold()
        preview_lower = request.preview_text.casefold()
        evidence: list[str] = []
        scores: list[float] = []

        project_score = 0.95 if request.project_code.casefold() in (
            filename_lower + "\n" + preview_lower
        ) else 0.0
        project_id = request.project_id if project_score >= self._threshold else None
        if project_id is not None:
            evidence.append(f"project code {request.project_code} found in source text")
            scores.append(project_score)

        category: str | None = None
        authority: str | None = None
        best_category_score = 0.0
        for candidate, keywords, candidate_authority in _CATEGORY_RULES:
            matched_filename = any(keyword.casefold() in filename_lower for keyword in keywords)
            matched_preview = any(keyword.casefold() in preview_lower for keyword in keywords)
            if matched_filename and matched_preview:
                score = 0.95
            elif matched_filename:
                score = 0.84
            elif matched_preview:
                score = 0.76
            else:
                score = 0.0
            if score > best_category_score:
                best_category_score = score
                if score >= self._threshold:
                    category = candidate
                    authority = candidate_authority
        if category is not None:
            evidence.append(f"document category inferred as {category}")
            scores.append(best_category_score)

        version_label: str | None = None
        version_score = 0.0
        filename_match = _VERSION_RE.search(request.filename)
        preview_match = _VERSION_RE.search(request.preview_text)
        match = filename_match or preview_match
        if match is not None:
            version_score = 0.95 if filename_match is not None else 0.80
            if version_score >= self._threshold:
                version_label = f"v{match.group(1)}"
                evidence.append(f"version token {version_label} found")
                scores.append(version_score)

        supersedes: UUID | None = None
        if category is not None:
            published = [
                version
                for version in request.existing_versions
                if version.document_category == category
                and version.lifecycle_status == "PUBLISHED"
            ]
            if len(published) == 1:
                supersedes = published[0].version_id
                evidence.append(f"single current published {category} version found")
                scores.append(0.90)

        confidence = min(scores) if scores else 0.0
        return MetadataSuggestion(
            suggested_project_id=project_id,
            suggested_document_category=category,
            suggested_version_label=version_label,
            suggested_authority_level=authority,
            suggested_supersedes_version_id=supersedes,
            confidence=confidence,
            evidence=tuple(evidence),
        )
