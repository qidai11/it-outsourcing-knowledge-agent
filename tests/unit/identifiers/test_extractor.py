from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.domain.identifiers import (
    ExtractedIdentifier,
    IdentifierSource,
    IdentifierType,
    ManualIdentifier,
)


def _pairs(values: tuple[ExtractedIdentifier, ...]) -> set[tuple[IdentifierType, str]]:
    return {(value.identifier_type, value.normalized_value) for value in values}


def test_extracts_all_gate7_identifier_types_deterministically() -> None:
    text = """
    项目 PRJ-ERP-2026 的需求 REQ-3.2.1 关联历史问题 BUG-1842。
    调用 /api/v2/import 时如果返回 E1027，请检查 ERR-IMPORT-004。
    数据写入 t_order_detail，关联字段 customer_id，当前版本 v1.8.3。
    """

    values = IdentifierExtractor().extract(text)

    issue_values = {
        value.normalized_value
        for value in values
        if value.identifier_type is IdentifierType.ISSUE_KEY
    }
    assert issue_values == {"BUG-1842"}

    assert {
        (IdentifierType.PROJECT_CODE, "PRJ-ERP-2026"),
        (IdentifierType.REQUIREMENT_ID, "REQ-3.2.1"),
        (IdentifierType.ISSUE_KEY, "BUG-1842"),
        (IdentifierType.API_PATH, "/api/v2/import"),
        (IdentifierType.DB_TABLE, "t_order_detail"),
        (IdentifierType.DB_COLUMN, "customer_id"),
        (IdentifierType.ERROR_CODE, "E1027"),
        (IdentifierType.ERROR_CODE, "ERR-IMPORT-004"),
        (IdentifierType.VERSION, "v1.8.3"),
    } <= _pairs(values)


def test_structure_labels_extract_non_prefixed_table_and_column() -> None:
    text = """
    表名：order_detail
    字段：external_customer_ref
    """

    values = IdentifierExtractor().extract(text)
    by_pair = {(value.identifier_type, value.normalized_value): value for value in values}

    assert by_pair[(IdentifierType.DB_TABLE, "order_detail")].source is IdentifierSource.STRUCTURE
    assert (
        by_pair[(IdentifierType.DB_COLUMN, "external_customer_ref")].source
        is IdentifierSource.STRUCTURE
    )


def test_manual_values_replace_automatic_values_of_same_type() -> None:
    text = "REQ-3.2.1 与 /api/v1/import 是旧的自动识别内容。"
    manual = (
        ManualIdentifier(
            identifier_type=IdentifierType.REQUIREMENT_ID,
            raw_value="REQ-9.9.9",
        ),
    )

    values = IdentifierExtractor().extract(text, manual_identifiers=manual)
    pairs = _pairs(values)

    assert (IdentifierType.REQUIREMENT_ID, "REQ-9.9.9") in pairs
    assert (IdentifierType.REQUIREMENT_ID, "REQ-3.2.1") not in pairs
    assert (IdentifierType.API_PATH, "/api/v1/import") in pairs
    req = next(value for value in values if value.identifier_type is IdentifierType.REQUIREMENT_ID)
    assert req.source is IdentifierSource.MANUAL


def test_duplicate_raw_mentions_collapse_to_one_normalized_identifier() -> None:
    values = IdentifierExtractor().extract("REQ-3.2.1, req-3.2.1, REQ-3.2.1")
    matches = [v for v in values if v.identifier_type is IdentifierType.REQUIREMENT_ID]
    assert len(matches) == 1
    assert matches[0].raw_value == "REQ-3.2.1"


def test_manual_override_can_remove_false_positive_type_entirely() -> None:
    values = IdentifierExtractor().extract(
        "临时变量 customer_id 不是数据库字段。",
        manual_override_types=(IdentifierType.DB_COLUMN,),
    )

    assert all(value.identifier_type is not IdentifierType.DB_COLUMN for value in values)


def test_sql_ddl_structure_extracts_table_and_columns_without_naming_conventions() -> None:
    text = """
    CREATE TABLE public.order_item (
        id UUID PRIMARY KEY,
        external_ref VARCHAR(64) NOT NULL,
        created_at TIMESTAMP NOT NULL
    );
    """

    values = IdentifierExtractor().extract(text)
    by_pair = {(value.identifier_type, value.normalized_value): value for value in values}

    assert by_pair[(IdentifierType.DB_TABLE, "order_item")].source is IdentifierSource.STRUCTURE
    assert by_pair[(IdentifierType.DB_COLUMN, "id")].source is IdentifierSource.STRUCTURE
    assert by_pair[(IdentifierType.DB_COLUMN, "external_ref")].source is IdentifierSource.STRUCTURE
