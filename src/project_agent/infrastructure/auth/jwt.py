from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from project_agent.application.services.authorization import AuthenticatedIdentity


class JwtIdentityError(ValueError):
    """Raised when an authentication token cannot be trusted."""


class JwtIdentityVerifier:
    """Minimal internal HS256 verifier for V1 authentication.

    The token is authentication-only: after cryptographic and registered-claim
    validation, only ``sub`` is returned. Any role/project/document claims in
    the token are deliberately discarded and must be reloaded from PostgreSQL.
    """

    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        leeway_seconds: int = 0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("JWT HS256 secret must be at least 32 bytes")
        self._secret = secret.encode("utf-8")
        self._issuer = issuer
        self._audience = audience
        self._leeway_seconds = max(0, leeway_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def verify_authorization_header(self, header: str) -> AuthenticatedIdentity:
        scheme, separator, token = header.strip().partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not token:
            raise JwtIdentityError("authorization header must use Bearer token")
        return self.verify(token)

    def verify(self, token: str) -> AuthenticatedIdentity:
        parts = token.split(".")
        if len(parts) != 3:
            raise JwtIdentityError("JWT must contain three segments")
        header_segment, payload_segment, signature_segment = parts
        header = self._decode_json_object(header_segment, "header")
        if header.get("alg") != "HS256":
            raise JwtIdentityError("JWT algorithm must be HS256")

        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        expected = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        try:
            supplied = self._decode_base64url(signature_segment)
        except ValueError as exc:
            raise JwtIdentityError("invalid JWT signature encoding") from exc
        if not hmac.compare_digest(expected, supplied):
            raise JwtIdentityError("JWT signature verification failed")

        payload = self._decode_json_object(payload_segment, "payload")
        self._validate_registered_claims(payload)
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise JwtIdentityError("JWT sub must be a UUID string")
        try:
            user_id = UUID(subject)
        except ValueError as exc:
            raise JwtIdentityError("JWT sub must be a UUID string") from exc
        return AuthenticatedIdentity(user_id=user_id)

    def _validate_registered_claims(self, payload: dict[str, Any]) -> None:
        if payload.get("iss") != self._issuer:
            raise JwtIdentityError("JWT issuer mismatch")
        audience = payload.get("aud")
        if isinstance(audience, str):
            audience_ok = audience == self._audience
        elif isinstance(audience, list):
            audience_ok = self._audience in audience
        else:
            audience_ok = False
        if not audience_ok:
            raise JwtIdentityError("JWT audience mismatch")

        now = self._clock().timestamp()
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            raise JwtIdentityError("JWT exp claim is required")
        if now >= float(exp) + self._leeway_seconds:
            raise JwtIdentityError("JWT has expired")
        nbf = payload.get("nbf")
        if nbf is not None:
            if not isinstance(nbf, (int, float)):
                raise JwtIdentityError("JWT nbf must be numeric")
            if now + self._leeway_seconds < float(nbf):
                raise JwtIdentityError("JWT is not active yet")

    @classmethod
    def _decode_json_object(cls, segment: str, label: str) -> dict[str, Any]:
        try:
            decoded = cls._decode_base64url(segment).decode("utf-8")
            value = json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JwtIdentityError(f"invalid JWT {label}") from exc
        if not isinstance(value, dict):
            raise JwtIdentityError(f"JWT {label} must be an object")
        return value

    @staticmethod
    def _decode_base64url(value: str) -> bytes:
        if not value:
            raise ValueError("empty base64url segment")
        padding = "=" * (-len(value) % 4)
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
