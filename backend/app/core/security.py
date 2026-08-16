"""Password hashing and JWT token primitives (spec §18.3/§19).

Access tokens are short-lived and stateless; refresh tokens are rotated and
tracked in ``refresh_sessions`` (hash-only storage, family revocation on replay).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


class TokenError(Exception):
    """Raised when a token is malformed, expired or has the wrong type."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(
    subject: str,
    signing_key: str,
    *,
    ttl_minutes: int = 15,
    extra: dict[str, str] | None = None,
) -> str:
    now = _now()
    payload: dict[str, object] = {
        "sub": subject,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, signing_key, algorithm=JWT_ALGORITHM)


def create_refresh_token(
    subject: str,
    signing_key: str,
    *,
    family_id: str,
    jti: str | None = None,
    ttl_days: int = 7,
) -> str:
    now = _now()
    payload: dict[str, object] = {
        "sub": subject,
        "type": REFRESH_TOKEN_TYPE,
        "family_id": family_id,
        "jti": jti or str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(days=ttl_days),
    }
    return jwt.encode(payload, signing_key, algorithm=JWT_ALGORITHM)


def decode_token(token: str, signing_key: str, *, expected_type: str) -> dict[str, object]:
    try:
        payload = jwt.decode(token, signing_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise TokenError(f"expected {expected_type} token")
    return payload


def token_subject(payload: dict[str, object]) -> str:
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise TokenError("token missing subject")
    return sub
