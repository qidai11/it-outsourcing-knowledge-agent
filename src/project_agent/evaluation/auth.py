"""Short-lived, identity-only evaluation JWTs; PostgreSQL remains the authz source.

This module deliberately does not expose extra claims or persist credentials.
The caller must supply the same secret/issuer/audience as the production API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_evaluation_jwt(
    *,
    user_id: UUID,
    secret: str,
    issuer: str,
    audience: str,
    expires_in_seconds: int = 900,
    now: datetime | None = None,
) -> str:
    """Create an HS256 token whose only identity/authorization input is ``sub``.

    Never add role, project, client, or company claims: the server reads
    current project memberships from PostgreSQL for every request.
    """
    if not 1 <= expires_in_seconds <= 3600:
        raise ValueError("expires_in_seconds must be between 1 and 3600")
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("HS256 secret must contain at least 32 bytes")
    if not issuer or not audience:
        raise ValueError("issuer and audience must be non-empty")
    at = now if now is not None else datetime.now(UTC)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    issued_at = int(at.timestamp())
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "sub": str(user_id),
        "iss": issuer,
        "aud": audience,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": issued_at + expires_in_seconds,
    }
    def encode(value: Mapping[str, object]) -> str:
        return _b64url(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
    signing_input = f"{encode(header)}.{encode(claims)}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256)
    return f"{signing_input}.{_b64url(signature.digest())}"


def mint_fixture_identity_jwt(
    *,
    state: Mapping[str, Any],
    user_alias: str,
    secret: str,
    issuer: str,
    audience: str,
    expires_in_seconds: int = 900,
    now: datetime | None = None,
) -> str:
    """Resolve one frozen fixture alias without inferring any authorization."""
    users = state.get("user_ids")
    if not isinstance(users, Mapping) or user_alias not in users:
        raise ValueError("unknown evaluation user alias")
    try:
        user_id = UUID(str(users[user_alias]))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("invalid evaluation user UUID") from exc
    return mint_evaluation_jwt(
        user_id=user_id,
        secret=secret,
        issuer=issuer,
        audience=audience,
        expires_in_seconds=expires_in_seconds,
        now=now,
    )
