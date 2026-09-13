from project_agent.domain.identifiers import IdentifierType, normalize_identifier


def test_normalizes_case_insensitive_business_identifiers() -> None:
    assert (
        normalize_identifier(IdentifierType.PROJECT_CODE, "prj-retail-alpha")
        == "PRJ-RETAIL-ALPHA"
    )
    assert normalize_identifier(IdentifierType.REQUIREMENT_ID, "req-3.2.1") == "REQ-3.2.1"
    assert normalize_identifier(IdentifierType.ISSUE_KEY, "alpha-102") == "ALPHA-102"
    assert normalize_identifier(IdentifierType.ERROR_CODE, "err-import-004") == "ERR-IMPORT-004"


def test_normalizes_database_identifiers_and_versions() -> None:
    assert (
        normalize_identifier(IdentifierType.DB_TABLE, '`Public`.`T_Order_Detail`')
        == "t_order_detail"
    )
    assert normalize_identifier(IdentifierType.DB_COLUMN, '"Customer_ID"') == "customer_id"
    assert normalize_identifier(IdentifierType.VERSION, " V1.8.3 ") == "v1.8.3"


def test_api_path_normalization_removes_query_fragment_and_trailing_slash() -> None:
    assert (
        normalize_identifier(IdentifierType.API_PATH, "/api/v1/import/?debug=1#section")
        == "/api/v1/import"
    )
