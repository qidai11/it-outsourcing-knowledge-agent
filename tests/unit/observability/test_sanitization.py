from project_agent.observability.sanitization import (
    REDACTED,
    safe_error_fields,
    sanitize_event_dict,
)


def test_sanitizer_redacts_sensitive_keys_recursively() -> None:
    event = {
        "event": "provider_failed",
        "authorization": "Bearer JWT-SENTINEL-4b03",
        "ragflow_api_key": "RAGFLOW-KEY-SENTINEL-91de",
        "query": "QUERY-SENTINEL-0be9",
        "nested": {
            "answer_text": "ANSWER-SENTINEL-ea24",
            "safe_count": 3,
            "items": [
                {"password": "PASSWORD-SENTINEL", "status_code": 500},
                "safe-value",
            ],
        },
    }

    sanitized = sanitize_event_dict(None, "error", event)

    assert sanitized["authorization"] == REDACTED
    assert sanitized["ragflow_api_key"] == REDACTED
    assert sanitized["query"] == REDACTED
    nested = sanitized["nested"]
    assert isinstance(nested, dict)
    assert nested["answer_text"] == REDACTED
    assert nested["safe_count"] == 3
    items = nested["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    assert first["password"] == REDACTED
    assert first["status_code"] == 500
    assert sanitized["event"] == "provider_failed"


def test_safe_error_fields_omit_exception_message_and_provider_body() -> None:
    sentinel = "PROVIDER-BODY-SENTINEL-6dca"
    fields = safe_error_fields(RuntimeError(sentinel))

    assert fields == {"error_type": "RuntimeError"}
    assert sentinel not in repr(fields)


def test_safe_error_fields_include_only_typed_bounded_metadata() -> None:
    class ProviderError(RuntimeError):
        status_code = 503
        code = "rate_limit"
        provider_body = "PROVIDER-BODY-SENTINEL"

    fields = safe_error_fields(ProviderError("unsafe provider message"))

    assert fields == {
        "error_type": "ProviderError",
        "status_code": 503,
        "error_code": "rate_limit",
    }
    assert "unsafe provider message" not in repr(fields)
    assert "PROVIDER-BODY-SENTINEL" not in repr(fields)
