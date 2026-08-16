"""Unit tests for security primitives (spec §18.3/§19)."""

from __future__ import annotations

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

KEY = "test-signing-key-0123456789"


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_password_rejects_none() -> None:
    assert verify_password("anything", None) is False


def test_access_token_roundtrip() -> None:
    token = create_access_token("user-123", KEY, ttl_minutes=15)
    payload = decode_token(token, KEY, expected_type="access")
    assert payload["sub"] == "user-123"


def test_refresh_token_roundtrip() -> None:
    token = create_refresh_token("user-123", KEY, family_id="fam-1", jti="jti-1")
    payload = decode_token(token, KEY, expected_type="refresh")
    assert payload["family_id"] == "fam-1"
    assert payload["jti"] == "jti-1"


def test_wrong_type_is_rejected() -> None:
    token = create_access_token("user-123", KEY)
    with pytest.raises(TokenError):
        decode_token(token, KEY, expected_type="refresh")


def test_expired_token_is_rejected() -> None:
    token = create_access_token("user-123", KEY, ttl_minutes=-1)
    with pytest.raises(TokenError):
        decode_token(token, KEY, expected_type="access")


def test_wrong_key_is_rejected() -> None:
    token = create_access_token("user-123", KEY)
    with pytest.raises(TokenError):
        decode_token(token, "another-key", expected_type="access")
