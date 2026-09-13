from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from project_agent.infrastructure.auth.jwt import JwtIdentityError, JwtIdentityVerifier


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token(payload: dict[str, object], *, secret: str = "s" * 32) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = (
        f"{_b64(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def test_verified_token_returns_only_trusted_user_identity() -> None:
    now = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)
    user_id = UUID("11111111-1111-4111-8111-111111111111")
    token = _token(
        {
            "sub": str(user_id),
            "iss": "project-agent",
            "aud": "project-agent-api",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            # These are deliberately forged authorization claims. They must
            # never appear in the returned identity.
            "role": "project_manager",
            "project_ids": ["beta-project"],
        }
    )
    verifier = JwtIdentityVerifier(
        secret="s" * 32,
        issuer="project-agent",
        audience="project-agent-api",
        clock=lambda: now,
    )

    identity = verifier.verify(token)

    assert identity.user_id == user_id
    assert identity.__dataclass_fields__.keys() == {"user_id"}


def test_invalid_signature_is_rejected() -> None:
    now = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)
    token = _token(
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "iss": "project-agent",
            "aud": "project-agent-api",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        secret="wrong-secret-that-is-still-long-enough",
    )
    verifier = JwtIdentityVerifier(
        secret="s" * 32,
        issuer="project-agent",
        audience="project-agent-api",
        clock=lambda: now,
    )

    with pytest.raises(JwtIdentityError, match="signature"):
        verifier.verify(token)


def test_expired_token_is_rejected() -> None:
    now = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)
    token = _token(
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "iss": "project-agent",
            "aud": "project-agent-api",
            "exp": int((now - timedelta(seconds=1)).timestamp()),
        }
    )
    verifier = JwtIdentityVerifier(
        secret="s" * 32,
        issuer="project-agent",
        audience="project-agent-api",
        clock=lambda: now,
    )

    with pytest.raises(JwtIdentityError, match="expired"):
        verifier.verify(token)


def test_token_expires_exactly_at_exp_boundary() -> None:
    now = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)
    token = _token(
        {
            "sub": "11111111-1111-4111-8111-111111111111",
            "iss": "project-agent",
            "aud": "project-agent-api",
            "exp": int(now.timestamp()),
        }
    )
    verifier = JwtIdentityVerifier(
        secret="s" * 32,
        issuer="project-agent",
        audience="project-agent-api",
        clock=lambda: now,
    )

    with pytest.raises(JwtIdentityError, match="expired"):
        verifier.verify(token)
