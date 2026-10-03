"""WS8 evaluation identity-only JWT contracts (no secrets are written to artifacts)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

USER = UUID("a07164dd-bf03-476f-9487-ddca771b6fd0")
SECRET = "t" * 48
NOW = datetime(2026, 9, 26, 8, 0, tzinfo=UTC)


def _jwt_parts(token: str) -> tuple[dict[str, str], dict[str, object], bytes]:
    header, payload, signature = token.split(".")
    def decode(part: str) -> bytes:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    expected = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    assert hmac.compare_digest(decode(signature), expected)
    return json.loads(decode(header)), json.loads(decode(payload)), decode(signature)


def test_evaluation_jwt_is_hs256_identity_only_with_short_expiry() -> None:
    from project_agent.evaluation.auth import mint_evaluation_jwt

    token = mint_evaluation_jwt(
        user_id=USER, secret=SECRET, issuer="ws8-test", audience="api-test",
        expires_in_seconds=600, now=NOW,
    )
    header, claims, _ = _jwt_parts(token)
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert claims == {
        "sub": str(USER), "iss": "ws8-test", "aud": "api-test",
        "iat": int(NOW.timestamp()), "nbf": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 600,
    }
    assert token == mint_evaluation_jwt(
        user_id=USER, secret=SECRET, issuer="ws8-test", audience="api-test",
        expires_in_seconds=600, now=NOW,
    )


@pytest.mark.parametrize("seconds", [0, -1, 3601])
def test_evaluation_jwt_rejects_unbounded_expiry(seconds: int) -> None:
    from project_agent.evaluation.auth import mint_evaluation_jwt

    with pytest.raises(ValueError, match="expires_in_seconds"):
        mint_evaluation_jwt(
            user_id=USER, secret=SECRET, issuer="issuer", audience="audience",
            expires_in_seconds=seconds, now=NOW,
        )


def test_evaluation_jwt_rejects_weak_secret() -> None:
    from project_agent.evaluation.auth import mint_evaluation_jwt

    with pytest.raises(ValueError, match="32"):
        mint_evaluation_jwt(
            user_id=USER, secret="short", issuer="issuer", audience="audience", now=NOW,
        )


def test_evaluation_jwt_resolves_only_frozen_fixture_identity() -> None:
    from project_agent.evaluation.auth import mint_fixture_identity_jwt

    state = {"user_ids": {"u-alpha": USER}}
    token = mint_fixture_identity_jwt(
        state=state, user_alias="u-alpha", secret=SECRET,
        issuer="ws8-test", audience="api-test", now=NOW,
    )
    _, claims, _ = _jwt_parts(token)
    assert claims["sub"] == str(USER)
    assert not ({"role", "project_id", "project_ids", "company_id"} & claims.keys())
    with pytest.raises(ValueError, match="unknown evaluation user alias"):
        mint_fixture_identity_jwt(
            state=state, user_alias="not-a-user", secret=SECRET,
            issuer="ws8-test", audience="api-test", now=NOW,
        )
