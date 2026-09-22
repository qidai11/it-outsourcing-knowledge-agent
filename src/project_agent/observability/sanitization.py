from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "jwt",
        "token",
        "api_key",
        "password",
        "secret",
        "credentials",
        "query",
        "query_text",
        "evidence",
        "evidence_text",
        "answer",
        "answer_text",
        "system_prompt",
        "user_prompt",
        "prompt",
        "request_body",
        "response_body",
        "provider_body",
        "provider_error_body",
    }
)

_MAX_ERROR_CODE_LENGTH = 64


def _normalize_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_")


def _is_sensitive_key(key: object) -> bool:
    normalized = _normalize_key(key)
    if normalized in SENSITIVE_KEYS:
        return True
    return normalized.endswith(
        ("_api_key", "_password", "_secret", "_credentials", "_jwt", "_token")
    )


def _sanitize_value(value: object) -> object:
    if isinstance(value, Mapping):
        sanitized: dict[object, object] = {}
        for key, nested in value.items():
            sanitized[key] = REDACTED if _is_sensitive_key(key) else _sanitize_value(nested)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_value(item) for item in value]
    return value


def sanitize_event_dict(
    logger: object,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> dict[str, Any]:
    """Redact protected structured-log fields recursively."""

    del logger, method_name
    sanitized = _sanitize_value(event_dict)
    if not isinstance(sanitized, dict):  # pragma: no cover - defensive type guarantee
        return dict(event_dict)
    return {str(key): value for key, value in sanitized.items()}


def _safe_error_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_ERROR_CODE_LENGTH:
        return None
    if not all(character.isalnum() or character in "._:-" for character in normalized):
        return None
    return normalized


def safe_error_fields(exc: BaseException) -> dict[str, object]:
    """Project an exception to bounded metadata without serializing its message/body."""

    fields: dict[str, object] = {"error_type": type(exc).__name__}

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        fields["status_code"] = status_code

    for attribute_name in ("error_code", "code"):
        error_code = _safe_error_code(getattr(exc, attribute_name, None))
        if error_code is not None:
            fields["error_code"] = error_code
            break

    return fields
