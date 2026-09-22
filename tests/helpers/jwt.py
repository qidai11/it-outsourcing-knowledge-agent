from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_hs256_token(
    *,
    user_id: UUID,
    secret: str,
    issuer: str,
    audience: str,
    expires_at: datetime,
    not_before: datetime | None = None,
    extra_claims: Mapping[str, object] | None = None,
) -> str:
    """Build a deterministic HS256 token for tests only."""

    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, object] = {
        "sub": str(user_id),
        "iss": issuer,
        "aud": audience,
        "exp": int(expires_at.timestamp()),
    }
    if not_before is not None:
        payload["nbf"] = int(not_before.timestamp())
    if extra_claims:
        payload.update(extra_claims)

    signing_input = (
        f"{_b64(json.dumps(header, separators=(',', ':'), sort_keys=True).encode())}."
        f"{_b64(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode())}"
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"
