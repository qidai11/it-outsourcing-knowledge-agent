from __future__ import annotations

from uuid import uuid4

from project_agent.application.services.metadata_suggestion import (
    ExistingDocumentVersion,
    MetadataSuggestionInput,
    MetadataSuggestionService,
)


def test_suggests_high_confidence_requirement_metadata_from_filename_and_preview() -> None:
    project_id = uuid4()
    old_version_id = uuid4()
    service = MetadataSuggestionService(confidence_threshold=0.75)

    suggestion = service.suggest(
        MetadataSuggestionInput(
            project_id=project_id,
            project_code="PRJ-RETAIL-ALPHA",
            filename="PRJ-RETAIL-ALPHA_requirement_baseline_v2.1.pdf",
            preview_text="需求规格说明书\n版本 V2.1\nREQ-3.2.1 登录失败锁定规则",
            existing_versions=(
                ExistingDocumentVersion(
                    version_id=old_version_id,
                    document_category="requirement_baseline",
                    version_label="v2.0",
                    lifecycle_status="PUBLISHED",
                ),
            ),
        )
    )

    assert suggestion.suggested_project_id == project_id
    assert suggestion.suggested_document_category == "requirement_baseline"
    assert suggestion.suggested_version_label == "v2.1"
    assert suggestion.suggested_authority_level == "requirement_baseline"
    assert suggestion.suggested_supersedes_version_id == old_version_id
    assert suggestion.confidence is not None and suggestion.confidence >= 0.75
    assert suggestion.evidence


def test_low_confidence_fields_remain_blank() -> None:
    service = MetadataSuggestionService(confidence_threshold=0.80)

    suggestion = service.suggest(
        MetadataSuggestionInput(
            project_id=uuid4(),
            project_code="PRJ-RETAIL-ALPHA",
            filename="notes.pdf",
            preview_text="一些讨论内容，没有项目编号、版本或正式文档类型。",
        )
    )

    assert suggestion.suggested_project_id is None
    assert suggestion.suggested_document_category is None
    assert suggestion.suggested_version_label is None
    assert suggestion.suggested_authority_level is None
    assert suggestion.suggested_supersedes_version_id is None


def test_suggestion_never_sets_lifecycle_status_or_confirms_authority() -> None:
    service = MetadataSuggestionService()
    suggestion = service.suggest(
        MetadataSuggestionInput(
            project_id=uuid4(),
            project_code="PRJ-RETAIL-ALPHA",
            filename="api_specification_v1.4.md",
            preview_text="API 接口设计 /api/v1/import",
        )
    )

    dumped = suggestion.model_dump()
    assert "lifecycle_status" not in dumped
    assert "confirmed_by" not in dumped
    assert "published" not in dumped
