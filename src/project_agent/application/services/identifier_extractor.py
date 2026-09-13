from __future__ import annotations

import re
from collections.abc import Iterable

from project_agent.domain.identifiers import (
    ExtractedIdentifier,
    IdentifierSource,
    IdentifierType,
    ManualIdentifier,
    normalize_identifier,
)


class IdentifierExtractor:
    """Deterministic identifier extraction for document/query text.

    Manual identifiers replace automatic extraction for the same identifier
    type. This makes the human-confirmed set authoritative rather than merely
    additive.
    """

    _patterns: tuple[tuple[IdentifierType, re.Pattern[str]], ...] = (
        (
            IdentifierType.PROJECT_CODE,
            re.compile(r"\bPRJ-[A-Z0-9]+(?:-[A-Z0-9]+)+\b", re.IGNORECASE),
        ),
        (
            IdentifierType.REQUIREMENT_ID,
            re.compile(r"\bREQ-\d+(?:\.\d+)+\b", re.IGNORECASE),
        ),
        (
            IdentifierType.ERROR_CODE,
            re.compile(r"\b(?:ERR-[A-Z0-9]+(?:-[A-Z0-9]+)+|E\d{3,7})\b", re.IGNORECASE),
        ),
        (
            IdentifierType.ISSUE_KEY,
            re.compile(
                r"(?<![A-Z0-9-])(?!(?:PRJ|REQ|ERR)-)[A-Z][A-Z0-9]{1,15}-\d+\b",
                re.IGNORECASE,
            ),
        ),
        (
            IdentifierType.API_PATH,
            re.compile(r"(?<![A-Za-z0-9])(/api/[A-Za-z0-9._~!$&'()*+,;=:@%{}\-/]+)"),
        ),
        (
            IdentifierType.DB_TABLE,
            re.compile(r"\b(?:t|tb|tbl)_[A-Za-z][A-Za-z0-9_]*\b", re.IGNORECASE),
        ),
        (
            IdentifierType.DB_COLUMN,
            re.compile(
                r"\b[A-Za-z][A-Za-z0-9_]*(?:_id|_code|_no|_at|_time|_date|_status|_flag|_ref)\b",
                re.IGNORECASE,
            ),
        ),
        (
            IdentifierType.VERSION,
            re.compile(r"\b[vV]\d+(?:\.\d+){1,3}\b"),
        ),
    )

    _table_label = re.compile(
        r"(?:表名|table(?:\s+name)?)\s*[：:=]\s*[`\"]?([A-Za-z_][A-Za-z0-9_.]*)[`\"]?",
        re.IGNORECASE,
    )
    _column_label = re.compile(
        r"(?:字段|列名|column(?:\s+name)?)\s*[：:=]\s*[`\"]?([A-Za-z_][A-Za-z0-9_.]*)[`\"]?",
        re.IGNORECASE,
    )
    _sql_table = re.compile(
        r"\b(?:CREATE|ALTER)\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"
        r"[`\"]?([A-Za-z_][A-Za-z0-9_.]*)[`\"]?",
        re.IGNORECASE,
    )
    _sql_column = re.compile(
        r"^[ \t]*[`\"]?([A-Za-z_][A-Za-z0-9_]*)[`\"]?[ \t]+"
        r"(?:UUID|BIGINT|SMALLINT|INT(?:EGER)?|VARCHAR|CHAR|TEXT|BOOLEAN|BOOL|"
        r"DATE|TIMESTAMP|TIMESTAMPTZ|NUMERIC|DECIMAL|REAL|DOUBLE|JSONB?|BYTEA)\b",
        re.IGNORECASE | re.MULTILINE,
    )

    def extract(
        self,
        text: str,
        *,
        manual_identifiers: Iterable[ManualIdentifier] = (),
        manual_override_types: Iterable[IdentifierType] = (),
        page_no: int | None = None,
        section: str | None = None,
    ) -> tuple[ExtractedIdentifier, ...]:
        automatic = self._extract_automatic(text, page_no=page_no, section=section)
        manual = tuple(
            ExtractedIdentifier(
                identifier_type=item.identifier_type,
                raw_value=item.raw_value,
                normalized_value=normalize_identifier(item.identifier_type, item.raw_value),
                source=IdentifierSource.MANUAL,
                confidence=1.0,
                page_no=item.page_no if item.page_no is not None else page_no,
                section=item.section if item.section is not None else section,
            )
            for item in manual_identifiers
        )

        manual_types = {item.identifier_type for item in manual}
        manual_types.update(manual_override_types)
        merged = [item for item in automatic if item.identifier_type not in manual_types]
        merged.extend(manual)
        return self._deduplicate(merged)

    def _extract_automatic(
        self,
        text: str,
        *,
        page_no: int | None,
        section: str | None,
    ) -> tuple[ExtractedIdentifier, ...]:
        values: list[ExtractedIdentifier] = []

        for identifier_type, pattern in self._patterns:
            for match in pattern.finditer(text):
                raw = match.group(0)
                values.append(
                    ExtractedIdentifier(
                        identifier_type=identifier_type,
                        raw_value=raw,
                        normalized_value=normalize_identifier(identifier_type, raw),
                        source=IdentifierSource.REGEX,
                        confidence=1.0,
                        page_no=page_no,
                        section=section,
                    )
                )

        values.extend(
            self._extract_labeled_structure(
                text,
                IdentifierType.DB_TABLE,
                self._table_label,
                page_no=page_no,
                section=section,
            )
        )
        values.extend(
            self._extract_labeled_structure(
                text,
                IdentifierType.DB_COLUMN,
                self._column_label,
                page_no=page_no,
                section=section,
            )
        )
        values.extend(
            self._extract_labeled_structure(
                text,
                IdentifierType.DB_TABLE,
                self._sql_table,
                page_no=page_no,
                section=section,
            )
        )
        values.extend(
            self._extract_labeled_structure(
                text,
                IdentifierType.DB_COLUMN,
                self._sql_column,
                page_no=page_no,
                section=section,
            )
        )
        return self._deduplicate(values)

    @staticmethod
    def _extract_labeled_structure(
        text: str,
        identifier_type: IdentifierType,
        pattern: re.Pattern[str],
        *,
        page_no: int | None,
        section: str | None,
    ) -> tuple[ExtractedIdentifier, ...]:
        return tuple(
            ExtractedIdentifier(
                identifier_type=identifier_type,
                raw_value=match.group(1),
                normalized_value=normalize_identifier(identifier_type, match.group(1)),
                source=IdentifierSource.STRUCTURE,
                confidence=1.0,
                page_no=page_no,
                section=section,
            )
            for match in pattern.finditer(text)
        )

    @staticmethod
    def _deduplicate(values: Iterable[ExtractedIdentifier]) -> tuple[ExtractedIdentifier, ...]:
        source_rank = {
            IdentifierSource.MANUAL: 3,
            IdentifierSource.STRUCTURE: 2,
            IdentifierSource.REGEX: 1,
        }
        # Stable grouping while preferring the strongest source for duplicate keys.
        by_key: dict[tuple[IdentifierType, str], ExtractedIdentifier] = {}
        order: list[tuple[IdentifierType, str]] = []
        for item in values:
            key = (item.identifier_type, item.normalized_value)
            previous = by_key.get(key)
            if previous is None:
                order.append(key)
                by_key[key] = item
            elif source_rank[item.source] > source_rank[previous.source]:
                by_key[key] = item
        return tuple(by_key[key] for key in order)
