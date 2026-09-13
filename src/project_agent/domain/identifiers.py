from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IdentifierType(StrEnum):
    PROJECT_CODE = "project_code"
    REQUIREMENT_ID = "requirement_id"
    ISSUE_KEY = "issue_key"
    API_PATH = "api_path"
    DB_TABLE = "db_table"
    DB_COLUMN = "db_column"
    ERROR_CODE = "error_code"
    VERSION = "version"


class IdentifierSource(StrEnum):
    REGEX = "regex"
    STRUCTURE = "structure"
    MANUAL = "manual"


class ManualIdentifier(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier_type: IdentifierType
    raw_value: str = Field(min_length=1)
    page_no: int | None = Field(default=None, ge=1)
    section: str | None = None


class ExtractedIdentifier(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier_type: IdentifierType
    raw_value: str
    normalized_value: str
    source: IdentifierSource
    confidence: float = Field(ge=0.0, le=1.0)
    page_no: int | None = Field(default=None, ge=1)
    section: str | None = None


class IdentifierRegistryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    company_id: UUID
    project_id: UUID
    document_version_id: UUID
    identifier_type: IdentifierType
    normalized_value: str
    raw_value: str
    source: IdentifierSource
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    page_no: int | None = None
    section: str | None = None


class IdentifierSpellingSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    normalized_value: str
    similarity: float = Field(ge=0.0, le=1.0)


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_BACKTICK_OR_QUOTE = re.compile(r"[`\"]")
_VERSION_RE = re.compile(r"^[vV]?\s*(\d+(?:\.\d+){1,3})$")


def normalize_identifier(identifier_type: IdentifierType, raw_value: str) -> str:
    """Return the canonical exact-match representation for an identifier.

    Normalization is intentionally deterministic and conservative. It does not
    perform fuzzy correction. Fuzzy spelling suggestions are a separate
    PostgreSQL pg_trgm operation and never alter the exact key.
    """

    value = raw_value.strip().strip(".,;:，。；：()[]{}<>《》")
    if not value:
        raise ValueError("identifier cannot be blank")

    if identifier_type in {
        IdentifierType.PROJECT_CODE,
        IdentifierType.REQUIREMENT_ID,
        IdentifierType.ISSUE_KEY,
        IdentifierType.ERROR_CODE,
    }:
        return value.upper()

    if identifier_type is IdentifierType.VERSION:
        match = _VERSION_RE.fullmatch(value)
        if match is None:
            return value.lower().replace(" ", "")
        return f"v{match.group(1)}"

    if identifier_type is IdentifierType.API_PATH:
        if _WINDOWS_DRIVE.match(value):
            raise ValueError("windows drive path is not an API identifier")
        # urlsplit also cleanly removes query/fragment from relative API paths.
        parsed = urlsplit(value)
        path = parsed.path or value.split("?", 1)[0].split("#", 1)[0]
        path = re.sub(r"/{2,}", "/", path)
        if len(path) > 1:
            path = path.rstrip("/")
        if not path.startswith("/"):
            path = f"/{path}"
        return path

    if identifier_type in {IdentifierType.DB_TABLE, IdentifierType.DB_COLUMN}:
        cleaned = _BACKTICK_OR_QUOTE.sub("", value).strip()
        if "." in cleaned:
            cleaned = cleaned.rsplit(".", 1)[1]
        return cleaned.lower()

    return value
