"""Detached human-signature verification for publication authorization.

The automated research process may prepare an immutable authorization request, but
it must never possess or invoke the human signer's private key.  This module therefore
contains verification only.  A caller must supply an externally trusted Ed25519 public
key fingerprint; accepting a key merely because it is embedded in an artifact would
allow a model or script to mint its own identity.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_DOMAIN = b"autoresearch-human-publication-authorization-v1\n"


class PublicationSignatureError(RuntimeError):
    """Raised when a detached human publication signature is not trustworthy."""


def publication_signature_message(authorization_request_hash: str) -> bytes:
    """Return the domain-separated bytes an external human signer must sign."""

    if not _HASH_PATTERN.fullmatch(authorization_request_hash):
        raise PublicationSignatureError(
            "authorization request hash must be a lowercase SHA-256 digest"
        )
    return _SIGNATURE_DOMAIN + authorization_request_hash.encode("ascii")


def ed25519_public_key_fingerprint(public_key_pem: str) -> str:
    """Hash the canonical DER public key used as the external trust anchor."""

    key = _load_ed25519_public_key(public_key_pem)
    der = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def verify_human_publication_signature(
    *,
    authorization_request_hash: str,
    signature_base64: str,
    public_key_pem: str,
    trusted_public_key_sha256: str,
) -> str:
    """Verify a detached signature against an out-of-band trusted key digest.

    The trusted digest is intentionally mandatory and is not inferred from the
    authorization artifact.  The returned value is the canonical public-key digest
    suitable for persisting in the verified authorization record.
    """

    if not _HASH_PATTERN.fullmatch(trusted_public_key_sha256):
        raise PublicationSignatureError(
            "trusted publication signer fingerprint must be a lowercase SHA-256 digest"
        )
    key = _load_ed25519_public_key(public_key_pem)
    actual_fingerprint = ed25519_public_key_fingerprint(public_key_pem)
    if not hmac.compare_digest(actual_fingerprint, trusted_public_key_sha256):
        raise PublicationSignatureError(
            "publication signer key does not match the external trust anchor"
        )
    try:
        signature = base64.b64decode(signature_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PublicationSignatureError(
            "publication signature is not canonical base64"
        ) from exc
    if len(signature) != 64:
        raise PublicationSignatureError("Ed25519 publication signature must be 64 bytes")
    if base64.b64encode(signature).decode("ascii") != signature_base64:
        raise PublicationSignatureError(
            "publication signature base64 is not in canonical form"
        )
    try:
        key.verify(
            signature,
            publication_signature_message(authorization_request_hash),
        )
    except InvalidSignature as exc:
        raise PublicationSignatureError(
            "detached human publication signature verification failed"
        ) from exc
    return actual_fingerprint


def _load_ed25519_public_key(public_key_pem: str) -> Ed25519PublicKey:
    if not public_key_pem.strip():
        raise PublicationSignatureError("publication signer public key is empty")
    try:
        loaded = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise PublicationSignatureError(
            "publication signer public key is not valid ASCII PEM"
        ) from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise PublicationSignatureError(
            "publication signer key must use the Ed25519 algorithm"
        )
    canonical_pem = loaded.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    if public_key_pem != canonical_pem:
        raise PublicationSignatureError(
            "publication signer key must be one canonical Ed25519 SPKI PEM block"
        )
    return loaded
