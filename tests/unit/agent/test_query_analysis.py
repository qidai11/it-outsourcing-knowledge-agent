from __future__ import annotations

from project_agent.agent.nodes.analyze_query import QueryAnalysisService
from project_agent.application.services.identifier_extractor import IdentifierExtractor
from project_agent.domain.identifiers import IdentifierType


def test_query_analysis_preserves_exact_identifiers_verbatim() -> None:
    query = (
        "PRJ-ERP-2026 请核对 REQ-3.2.1、BUG-1842、/api/v2/import、"
        "customer_id、t_order_detail、E1027 和 v1.8.3。"
    )

    analysis = QueryAnalysisService(IdentifierExtractor()).analyze(query)

    by_type = {(item.identifier_type, item.raw_value) for item in analysis.exact_identifiers}
    expected = {
        (IdentifierType.PROJECT_CODE, "PRJ-ERP-2026"),
        (IdentifierType.REQUIREMENT_ID, "REQ-3.2.1"),
        (IdentifierType.ISSUE_KEY, "BUG-1842"),
        (IdentifierType.API_PATH, "/api/v2/import"),
        (IdentifierType.DB_COLUMN, "customer_id"),
        (IdentifierType.DB_TABLE, "t_order_detail"),
        (IdentifierType.ERROR_CODE, "E1027"),
        (IdentifierType.VERSION, "v1.8.3"),
    }
    assert expected.issubset(by_type)
    assert analysis.original_query == query
    assert analysis.standalone_query == query


def test_query_analysis_does_not_turn_nested_project_or_error_parts_into_issue_keys() -> None:
    analysis = QueryAnalysisService(IdentifierExtractor()).analyze(
        "PRJ-ERP-2026 报错 ERR-IMPORT-004"
    )
    issue_values = {
        item.normalized_value
        for item in analysis.exact_identifiers
        if item.identifier_type is IdentifierType.ISSUE_KEY
    }
    assert "ERP-2026" not in issue_values
    assert "IMPORT-004" not in issue_values
