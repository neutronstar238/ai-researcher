"""Tests for the external human publication-signature trust boundary."""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autoresearch.competition.publication_signature import (
    PublicationSignatureError,
    ed25519_public_key_fingerprint,
    publication_signature_message,
    verify_human_publication_signature,
)


def _key_material() -> tuple[Ed25519PrivateKey, str, str]:
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_key, public_pem, ed25519_public_key_fingerprint(public_pem)


def _signature(private_key: Ed25519PrivateKey, request_hash: str) -> str:
    return base64.b64encode(
        private_key.sign(publication_signature_message(request_hash))
    ).decode("ascii")


def test_verifies_only_the_externally_trusted_ed25519_key() -> None:
    private_key, public_pem, fingerprint = _key_material()
    request_hash = hashlib.sha256(b"objective-ready-manifest").hexdigest()

    assert (
        verify_human_publication_signature(
            authorization_request_hash=request_hash,
            signature_base64=_signature(private_key, request_hash),
            public_key_pem=public_pem,
            trusted_public_key_sha256=fingerprint,
        )
        == fingerprint
    )


def test_self_minted_key_cannot_replace_the_external_trust_anchor() -> None:
    attacker_private, attacker_pem, _ = _key_material()
    _, _, trusted_fingerprint = _key_material()
    request_hash = hashlib.sha256(b"objective-ready-manifest").hexdigest()

    with pytest.raises(PublicationSignatureError, match="external trust anchor"):
        verify_human_publication_signature(
            authorization_request_hash=request_hash,
            signature_base64=_signature(attacker_private, request_hash),
            public_key_pem=attacker_pem,
            trusted_public_key_sha256=trusted_fingerprint,
        )


def test_signature_cannot_be_replayed_for_another_request() -> None:
    private_key, public_pem, fingerprint = _key_material()
    first_hash = hashlib.sha256(b"first-manifest").hexdigest()
    second_hash = hashlib.sha256(b"second-manifest").hexdigest()

    with pytest.raises(PublicationSignatureError, match="verification failed"):
        verify_human_publication_signature(
            authorization_request_hash=second_hash,
            signature_base64=_signature(private_key, first_hash),
            public_key_pem=public_pem,
            trusted_public_key_sha256=fingerprint,
        )


@pytest.mark.parametrize(
    "signature",
    ("not base64!", base64.b64encode(b"short").decode("ascii")),
)
def test_malformed_signature_fails_closed(signature: str) -> None:
    _, public_pem, fingerprint = _key_material()
    request_hash = hashlib.sha256(b"objective-ready-manifest").hexdigest()

    with pytest.raises(PublicationSignatureError):
        verify_human_publication_signature(
            authorization_request_hash=request_hash,
            signature_base64=signature,
            public_key_pem=public_pem,
            trusted_public_key_sha256=fingerprint,
        )


def test_noncanonical_base64_padding_bits_are_rejected() -> None:
    private_key, public_pem, fingerprint = _key_material()
    request_hash = hashlib.sha256(b"objective-ready-manifest").hexdigest()
    canonical = _signature(private_key, request_hash)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    final_value = alphabet.index(canonical[-3])
    noncanonical = canonical[:-3] + alphabet[final_value + 1] + "=="
    assert base64.b64decode(noncanonical, validate=True) == base64.b64decode(
        canonical, validate=True
    )

    with pytest.raises(PublicationSignatureError, match="canonical form"):
        verify_human_publication_signature(
            authorization_request_hash=request_hash,
            signature_base64=noncanonical,
            public_key_pem=public_pem,
            trusted_public_key_sha256=fingerprint,
        )


@pytest.mark.parametrize("suffix", ("\n", "JUNK", "\n-----BEGIN PUBLIC KEY-----"))
def test_public_key_requires_one_exact_canonical_pem_block(suffix: str) -> None:
    _, public_pem, _ = _key_material()

    with pytest.raises(PublicationSignatureError, match="canonical"):
        ed25519_public_key_fingerprint(public_pem + suffix)


def test_non_ed25519_key_is_rejected() -> None:
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

    public_pem = generate_private_key(
        public_exponent=65537,
        key_size=2048,
    ).public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")

    with pytest.raises(PublicationSignatureError, match="Ed25519"):
        ed25519_public_key_fingerprint(public_pem)
