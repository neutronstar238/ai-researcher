"""Independent signed transport-gateway contracts and verification.

The ordinary LLM client runs in the same process as the research controller.  Its
HTTP trace is useful for mutation detection, but it cannot prove that an external
provider was contacted.  This module defines the strictly narrower evidence
boundary for an independently operated gateway:

* the controller commits exact request bytes and benchmark lineage before transport;
* the gateway observes the HTTPS exchange and signs a canonical receipt with an
  Ed25519 key that is never available to this process; and
* a verifier accepts the receipt only against out-of-band trust anchors, a trusted
  clock, and a persistent one-use nonce ledger.

There is deliberately no private-key loader, key generator, or signing function in
this module.  An embedded public key is untrusted metadata until its canonical SPKI
fingerprint matches the fingerprint supplied by the verifier's external policy.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import os
import re
import urllib.parse
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ConfigDict, Field, JsonValue, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)

_SIGNATURE_DOMAIN = b"autoresearch-adaptive-transport-gateway-receipt-v1\n"
_SIGNATURE_DOMAIN_LABEL = "autoresearch-adaptive-transport-gateway-receipt-v1"
_REPLAY_ENTRY_DOMAIN = b"autoresearch-adaptive-transport-gateway-replay-v1\n"
_UTC_SECONDS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_NONCE_PATTERN = re.compile(r"^[0-9a-f]{32,64}$")
_HOST_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_MAX_RECEIPT_AGE = timedelta(minutes=5)
_MAX_FUTURE_SKEW = timedelta(seconds=30)
_MAX_GATEWAY_DURATION = timedelta(minutes=5)


class AdaptiveTransportGatewayError(RuntimeError):
    """Raised when signed gateway evidence is absent, stale, or untrustworthy."""


class _FrozenGatewayContract(KernelContract):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdaptiveTransportRequestCommitment(_FrozenGatewayContract):
    """Exact, pre-transport request and benchmark-lineage commitment."""

    schema_version: Literal["adaptive-transport-request-commitment-v1"] = (
        "adaptive-transport-request-commitment-v1"
    )
    request_id: str = Field(pattern=_REQUEST_ID_PATTERN.pattern)
    provider_name: StableId
    model_name: StableId
    request_method: Literal["POST"] = "POST"
    request_url: str = Field(min_length=1, max_length=2_048)
    request_origin: str = Field(min_length=1, max_length=512)
    request_payload_sha256: Sha256
    request_payload_size_bytes: int = Field(ge=0)
    request_messages_sha256: Sha256
    nonce: str = Field(pattern=_NONCE_PATTERN.pattern)
    issued_at_utc: str = Field(pattern=_UTC_SECONDS_PATTERN.pattern)
    cell_id: StableId
    trajectory_id: StableId
    reservation_id: StableId
    reservation_hash: Sha256
    pre_call_id: StableId
    pre_call_hash: Sha256
    max_redirects: int = Field(ge=0, le=3)
    commitment_hash: Sha256

    @model_validator(mode="after")
    def _validate_commitment(self) -> AdaptiveTransportRequestCommitment:
        _require_request_id(self.request_id)
        _parse_canonical_utc(self.issued_at_utc)
        origin = _canonical_public_https_origin(self.request_origin)
        if origin != self.request_origin:
            raise ValueError("request origin is not canonical")
        request_url = _canonical_public_https_url(self.request_url)
        if request_url != self.request_url:
            raise ValueError("request URL is not canonical")
        if _origin_from_url(request_url) != origin:
            raise ValueError("request URL does not match the committed origin")
        if self.commitment_hash != _calculated_hash(self, "commitment_hash"):
            raise ValueError("transport request commitment hash mismatch")
        return self


class AdaptiveTransportGatewayCompletionPayload(_FrozenGatewayContract):
    """Controller-visible fields parsed from the same signed HTTP response body."""

    schema_version: Literal["adaptive-transport-gateway-completion-payload-v2"] = (
        "adaptive-transport-gateway-completion-payload-v2"
    )
    provider_response_model: str = Field(min_length=1, max_length=256)
    provider_response_model_utf8_sha256: Sha256
    visible_output: str = Field(min_length=1)
    reasoning_output: str
    usage: dict[str, JsonValue]
    visible_output_utf8_sha256: Sha256
    reasoning_output_utf8_sha256: Sha256
    usage_canonical_json_sha256: Sha256
    completion_payload_hash: Sha256

    @model_validator(mode="after")
    def _validate_completion(self) -> AdaptiveTransportGatewayCompletionPayload:
        if self.provider_response_model_utf8_sha256 != _sha256_bytes(
            self.provider_response_model.encode("utf-8")
        ):
            raise ValueError("gateway provider response model hash mismatch")
        if self.visible_output != self.visible_output.strip():
            raise ValueError("gateway visible output must match the client-normalized text")
        if self.visible_output_utf8_sha256 != _sha256_bytes(self.visible_output.encode("utf-8")):
            raise ValueError("gateway visible output hash mismatch")
        if self.reasoning_output_utf8_sha256 != _sha256_bytes(
            self.reasoning_output.encode("utf-8")
        ):
            raise ValueError("gateway reasoning output hash mismatch")
        if self.usage_canonical_json_sha256 != canonical_sha256(self.usage):
            raise ValueError("gateway completion usage hash mismatch")
        if self.completion_payload_hash != _calculated_hash(self, "completion_payload_hash"):
            raise ValueError("gateway completion payload hash mismatch")
        return self


class AdaptiveTransportRedirectHop(_FrozenGatewayContract):
    """One explicitly permitted, method-preserving HTTPS redirect."""

    sequence: int = Field(ge=1, le=3)
    source_url: str = Field(min_length=1, max_length=2_048)
    status_code: Literal[307, 308]
    target_url: str = Field(min_length=1, max_length=2_048)
    method_before: Literal["POST"] = "POST"
    method_after: Literal["POST"] = "POST"

    @model_validator(mode="after")
    def _validate_redirect(self) -> AdaptiveTransportRedirectHop:
        source = _canonical_public_https_url(self.source_url)
        target = _canonical_public_https_url(self.target_url)
        if source != self.source_url or target != self.target_url:
            raise ValueError("redirect URLs must use their canonical form")
        if _origin_from_url(source) != _origin_from_url(target):
            raise ValueError("cross-origin redirects are forbidden")
        if source == target:
            raise ValueError("redirect source and target must differ")
        return self


class AdaptiveTransportGatewayReceipt(_FrozenGatewayContract):
    """Unsigned canonical facts that an independent gateway must sign."""

    schema_version: Literal["adaptive-transport-gateway-receipt-v2"] = (
        "adaptive-transport-gateway-receipt-v2"
    )
    gateway_receipt_id: StableId
    request_commitment: AdaptiveTransportRequestCommitment
    request_commitment_hash: Sha256
    transmitted_request_sha256: Sha256
    transmitted_request_size_bytes: int = Field(ge=0)
    completed_at_utc: str = Field(pattern=_UTC_SECONDS_PATTERN.pattern)
    final_url: str = Field(min_length=1, max_length=2_048)
    final_method: Literal["POST"] = "POST"
    http_status_code: int = Field(ge=100, le=599)
    connected_ip: str = Field(min_length=2, max_length=64)
    tls_peer_certificate_sha256: Sha256 | None = None
    tls_peer_spki_sha256: Sha256 | None = None
    tls_protocol: Literal["TLSv1.2", "TLSv1.3"]
    tls_chain_verified: Literal[True] = True
    tls_hostname_verified: Literal[True] = True
    redirect_chain: tuple[AdaptiveTransportRedirectHop, ...] = ()
    response_body_sha256: Sha256
    response_body_size_bytes: int = Field(ge=0)
    provider_response_id_sha256: Sha256 | None = None
    provider_response_model: str | None = Field(default=None, min_length=1, max_length=256)
    provider_response_model_utf8_sha256: Sha256 | None = None
    provider_response_model_matches_committed_model: bool
    completion_fields_available: bool
    visible_output_utf8_sha256: Sha256 | None = None
    reasoning_output_utf8_sha256: Sha256 | None = None
    usage_canonical_json_sha256: Sha256 | None = None
    gateway_build_sha256: Sha256
    gateway_source_sha256: Sha256
    gateway_nonce_first_seen: Literal[True] = True
    gateway_clock_checked: Literal[True] = True
    complete_response_body_read: Literal[True] = True
    receipt_hash: Sha256

    @model_validator(mode="after")
    def _validate_receipt(self) -> AdaptiveTransportGatewayReceipt:
        commitment = self.request_commitment
        if self.request_commitment_hash != commitment.commitment_hash:
            raise ValueError("gateway receipt binds the wrong request commitment")
        if (
            self.transmitted_request_sha256,
            self.transmitted_request_size_bytes,
        ) != (
            commitment.request_payload_sha256,
            commitment.request_payload_size_bytes,
        ):
            raise ValueError("gateway transmitted bytes differ from the commitment")
        issued_at = _parse_canonical_utc(commitment.issued_at_utc)
        completed_at = _parse_canonical_utc(self.completed_at_utc)
        if completed_at < issued_at:
            raise ValueError("gateway completion predates the request commitment")
        if completed_at - issued_at > _MAX_GATEWAY_DURATION:
            raise ValueError("gateway exchange exceeded the fixed duration bound")
        final_url = _canonical_public_https_url(self.final_url)
        if final_url != self.final_url:
            raise ValueError("gateway final URL is not canonical")
        if _origin_from_url(final_url) != commitment.request_origin:
            raise ValueError("gateway final URL left the committed origin")
        _require_global_ip(self.connected_ip)
        if self.tls_peer_certificate_sha256 is None and self.tls_peer_spki_sha256 is None:
            raise ValueError("gateway receipt needs a TLS certificate or SPKI fingerprint")
        if (self.provider_response_model is None) != (
            self.provider_response_model_utf8_sha256 is None
        ):
            raise ValueError("gateway provider response model projection is incomplete")
        if self.provider_response_model is not None:
            expected_model_hash = _sha256_bytes(self.provider_response_model.encode("utf-8"))
            if self.provider_response_model_utf8_sha256 != expected_model_hash:
                raise ValueError("gateway provider response model hash mismatch")
        expected_model_match = self.provider_response_model is not None and hmac.compare_digest(
            self.provider_response_model,
            commitment.model_name,
        )
        if self.provider_response_model_matches_committed_model != expected_model_match:
            raise ValueError("gateway response model match claim is not mechanical")
        completion_hashes = (
            self.visible_output_utf8_sha256,
            self.reasoning_output_utf8_sha256,
            self.usage_canonical_json_sha256,
        )
        if self.completion_fields_available != all(
            value is not None for value in completion_hashes
        ):
            raise ValueError("gateway completion projection hashes are incomplete")
        if (200 <= self.http_status_code < 300) != self.completion_fields_available:
            raise ValueError(
                "successful provider HTTP responses need replayable completion projections"
            )
        if self.completion_fields_available and not expected_model_match:
            raise ValueError(
                "successful provider response model must exactly match the committed model"
            )
        if len(self.redirect_chain) > commitment.max_redirects:
            raise ValueError("gateway followed more redirects than the request allowed")
        expected_source = commitment.request_url
        for expected_sequence, hop in enumerate(self.redirect_chain, start=1):
            if hop.sequence != expected_sequence:
                raise ValueError("gateway redirect sequence is not contiguous")
            if hop.source_url != expected_source:
                raise ValueError("gateway redirect chain is disconnected")
            if _origin_from_url(hop.target_url) != commitment.request_origin:
                raise ValueError("gateway redirect target left the committed origin")
            expected_source = hop.target_url
        if self.final_url != expected_source:
            raise ValueError("gateway final URL disagrees with its redirect chain")
        if self.receipt_hash != _calculated_hash(self, "receipt_hash"):
            raise ValueError("transport gateway receipt hash mismatch")
        return self


class AdaptiveTransportGatewayFailureReceipt(_FrozenGatewayContract):
    """Signed evidence that the gateway failed before a complete HTTP response."""

    schema_version: Literal["adaptive-transport-gateway-failure-receipt-v1"] = (
        "adaptive-transport-gateway-failure-receipt-v1"
    )
    gateway_receipt_id: StableId
    request_commitment: AdaptiveTransportRequestCommitment
    request_commitment_hash: Sha256
    observed_request_sha256: Sha256
    observed_request_size_bytes: int = Field(ge=0)
    failed_at_utc: str = Field(pattern=_UTC_SECONDS_PATTERN.pattern)
    failure_stage: Literal[
        "dns_resolution",
        "tcp_connect",
        "tls_handshake",
        "request_write",
        "response_headers",
    ]
    attempted_url: str = Field(min_length=1, max_length=2_048)
    attempted_method: Literal["POST"] = "POST"
    connected_ip: str | None = Field(default=None, min_length=2, max_length=64)
    tls_peer_certificate_sha256: Sha256 | None = None
    tls_peer_spki_sha256: Sha256 | None = None
    redirect_chain: tuple[AdaptiveTransportRedirectHop, ...] = ()
    failure_error_type_sha256: Sha256
    failure_error_message_sha256: Sha256
    gateway_build_sha256: Sha256
    gateway_source_sha256: Sha256
    gateway_nonce_first_seen: Literal[True] = True
    gateway_clock_checked: Literal[True] = True
    http_response_received: Literal[False] = False
    completion_fields_available: Literal[False] = False
    receipt_hash: Sha256

    @model_validator(mode="after")
    def _validate_failure_receipt(self) -> AdaptiveTransportGatewayFailureReceipt:
        commitment = self.request_commitment
        if self.request_commitment_hash != commitment.commitment_hash:
            raise ValueError("gateway failure binds the wrong request commitment")
        if (self.observed_request_sha256, self.observed_request_size_bytes) != (
            commitment.request_payload_sha256,
            commitment.request_payload_size_bytes,
        ):
            raise ValueError("gateway failure observed bytes differ from the commitment")
        issued_at = _parse_canonical_utc(commitment.issued_at_utc)
        failed_at = _parse_canonical_utc(self.failed_at_utc)
        if failed_at < issued_at:
            raise ValueError("gateway failure predates the request commitment")
        if failed_at - issued_at > _MAX_GATEWAY_DURATION:
            raise ValueError("gateway failure exceeded the fixed duration bound")
        attempted_url = _canonical_public_https_url(self.attempted_url)
        if attempted_url != self.attempted_url:
            raise ValueError("gateway attempted URL is not canonical")
        if _origin_from_url(attempted_url) != commitment.request_origin:
            raise ValueError("gateway failure left the committed origin")
        if len(self.redirect_chain) > commitment.max_redirects:
            raise ValueError("gateway failure followed too many redirects")
        expected_source = commitment.request_url
        for expected_sequence, hop in enumerate(self.redirect_chain, start=1):
            if hop.sequence != expected_sequence or hop.source_url != expected_source:
                raise ValueError("gateway failure redirect chain is disconnected")
            if _origin_from_url(hop.target_url) != commitment.request_origin:
                raise ValueError("gateway failure redirect left the committed origin")
            expected_source = hop.target_url
        if attempted_url != expected_source:
            raise ValueError("gateway attempted URL disagrees with its redirect chain")
        if self.connected_ip is not None:
            _require_global_ip(self.connected_ip)
        if self.failure_stage == "dns_resolution" and any(
            value is not None
            for value in (
                self.connected_ip,
                self.tls_peer_certificate_sha256,
                self.tls_peer_spki_sha256,
            )
        ):
            raise ValueError("DNS failure cannot claim connection or TLS evidence")
        if self.failure_stage == "tcp_connect" and (
            self.tls_peer_certificate_sha256 is not None or self.tls_peer_spki_sha256 is not None
        ):
            raise ValueError("TCP failure cannot claim TLS peer evidence")
        if self.failure_stage in {"request_write", "response_headers"} and (
            self.connected_ip is None
            or (self.tls_peer_certificate_sha256 is None and self.tls_peer_spki_sha256 is None)
        ):
            raise ValueError("post-TLS failure lacks its connection/TLS peer binding")
        if self.receipt_hash != _calculated_hash(self, "receipt_hash"):
            raise ValueError("transport gateway failure receipt hash mismatch")
        return self


AdaptiveTransportGatewayReceiptEvidence = (
    AdaptiveTransportGatewayReceipt | AdaptiveTransportGatewayFailureReceipt
)


class SignedAdaptiveTransportGatewayReceipt(_FrozenGatewayContract):
    """Detached Ed25519 envelope; the embedded public key is not a trust root."""

    schema_version: Literal["signed-adaptive-transport-gateway-receipt-v1"] = (
        "signed-adaptive-transport-gateway-receipt-v1"
    )
    receipt: AdaptiveTransportGatewayReceiptEvidence
    signature_algorithm: Literal["Ed25519"] = "Ed25519"
    signature_domain: Literal["autoresearch-adaptive-transport-gateway-receipt-v1"] = (
        "autoresearch-adaptive-transport-gateway-receipt-v1"
    )
    gateway_public_key_pem: str = Field(min_length=1, max_length=1_024)
    embedded_gateway_public_key_sha256_untrusted: Sha256
    signature_base64: str = Field(min_length=88, max_length=88)
    envelope_hash: Sha256

    @model_validator(mode="after")
    def _validate_envelope(self) -> SignedAdaptiveTransportGatewayReceipt:
        key, fingerprint = _load_canonical_ed25519_public_key(self.gateway_public_key_pem)
        del key
        if fingerprint != self.embedded_gateway_public_key_sha256_untrusted:
            raise ValueError("embedded gateway public-key fingerprint mismatch")
        _decode_canonical_signature(self.signature_base64)
        if self.envelope_hash != _calculated_hash(self, "envelope_hash"):
            raise ValueError("signed transport gateway envelope hash mismatch")
        return self


class VerifiedAdaptiveTransportGatewayAttestation(_FrozenGatewayContract):
    """One-time acceptance returned only after external-policy verification."""

    schema_version: Literal["verified-adaptive-transport-gateway-attestation-v1"] = (
        "verified-adaptive-transport-gateway-attestation-v1"
    )
    receipt_hash: Sha256
    envelope_hash: Sha256
    request_commitment_hash: Sha256
    trusted_gateway_public_key_sha256: Sha256
    trusted_gateway_build_sha256: Sha256
    trusted_gateway_source_sha256: Sha256
    verified_at_utc: str = Field(pattern=_UTC_SECONDS_PATTERN.pattern)
    outcome: Literal["http_response", "transport_failure"]
    http_response_received: bool
    provider_completion_eligible: bool
    signature_verified: Literal[True] = True
    request_bytes_and_lineage_verified: Literal[True] = True
    https_origin_policy_verified: Literal[True] = True
    tls_peer_binding_verified: Literal[True] = True
    nonce_accepted_once: Literal[True] = True
    independent_external_gateway_verified: Literal[True] = True
    process_local_client_trace_promoted: Literal[False] = False
    formal_transport_eligible: Literal[True] = True
    attestation_hash: Sha256

    @model_validator(mode="after")
    def _validate_attestation(self) -> VerifiedAdaptiveTransportGatewayAttestation:
        _parse_canonical_utc(self.verified_at_utc)
        if self.outcome == "transport_failure" and (
            self.http_response_received or self.provider_completion_eligible
        ):
            raise ValueError("transport failure cannot claim a provider completion")
        if self.outcome == "http_response" and not self.http_response_received:
            raise ValueError("HTTP-response outcome must acknowledge its response")
        if self.provider_completion_eligible and not self.http_response_received:
            raise ValueError("provider completion requires an HTTP response")
        if self.attestation_hash != _calculated_hash(self, "attestation_hash"):
            raise ValueError("verified transport attestation hash mismatch")
        return self


class TransportGatewayReplayLedgerEntry(_FrozenGatewayContract):
    """Local create-once anti-replay record, not independent acceptance evidence.

    The entry is not externally signed and does not establish gateway identity.  The
    gateway Ed25519 signature checked against out-of-band trust anchors is the formal
    transport basis; this record only detects reuse or local ledger mutation.
    """

    schema_version: Literal["adaptive-transport-gateway-local-antireplay-entry-v3"] = (
        "adaptive-transport-gateway-local-antireplay-entry-v3"
    )
    replay_key: Sha256
    signer_fingerprint: Sha256
    nonce: str = Field(pattern=_NONCE_PATTERN.pattern)
    receipt_hash: Sha256
    envelope_hash: Sha256
    commitment_hash: Sha256
    attestation_hash: Sha256
    observed_at_utc: str = Field(pattern=_UTC_SECONDS_PATTERN.pattern)
    entry_hash: Sha256

    @model_validator(mode="after")
    def _validate_entry(self) -> TransportGatewayReplayLedgerEntry:
        _parse_canonical_utc(self.observed_at_utc)
        if self.replay_key != _replay_key(self.signer_fingerprint, self.nonce):
            raise ValueError("transport anti-replay entry key mismatch")
        if self.entry_hash != _calculated_hash(self, "entry_hash"):
            raise ValueError("transport anti-replay entry hash mismatch")
        return self


class PostRunAdaptiveTransportGatewayReplay(_FrozenGatewayContract):
    """Read-only revalidation of signed evidence plus local anti-replay integrity."""

    schema_version: Literal["post-run-adaptive-transport-gateway-replay-v2"] = (
        "post-run-adaptive-transport-gateway-replay-v2"
    )
    receipt_hash: Sha256
    envelope_hash: Sha256
    request_commitment_hash: Sha256
    accepted_attestation_hash: Sha256
    local_antireplay_entry_hash: Sha256
    original_accepted_at_utc: str = Field(pattern=_UTC_SECONDS_PATTERN.pattern)
    signature_and_external_policy_reverified: Literal[True] = True
    original_freshness_replayed: Literal[True] = True
    local_antireplay_integrity_replayed: Literal[True] = True
    local_ledger_is_independent_acceptance_evidence: Literal[False] = False
    nonce_was_not_reconsumed: Literal[True] = True
    formal_transport_eligible: Literal[True] = True
    provider_completion_eligible: bool
    replay_hash: Sha256

    @model_validator(mode="after")
    def _validate_replay(self) -> PostRunAdaptiveTransportGatewayReplay:
        _parse_canonical_utc(self.original_accepted_at_utc)
        if self.replay_hash != _calculated_hash(self, "replay_hash"):
            raise ValueError("post-run gateway replay hash mismatch")
        return self


class TransportGatewayReplayLedger:
    """Persistent local anti-replay ledger using atomic create-once entries.

    This caller-writable store is integrity state, not an independent signer or
    identity root.  It cannot replace the externally trusted gateway signature.
    """

    def __init__(self, root: Path) -> None:
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise AdaptiveTransportGatewayError(
                "transport replay ledger root must be a real directory"
            )
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise AdaptiveTransportGatewayError(
                "transport replay ledger root must not be a symlink"
            )
        self._root = root.resolve(strict=True)

    @property
    def root(self) -> Path:
        return self._root

    def consume_once(
        self,
        *,
        signer_fingerprint: Sha256,
        nonce: str,
        receipt_hash: Sha256,
        envelope_hash: Sha256,
        commitment_hash: Sha256,
        attestation_hash: Sha256,
        observed_at_utc: str,
    ) -> str:
        """Atomically consume a signer-scoped nonce, rejecting every replay."""

        if not _NONCE_PATTERN.fullmatch(nonce):
            raise AdaptiveTransportGatewayError("gateway nonce is not canonical")
        _require_sha256(signer_fingerprint, "gateway signer fingerprint")
        _require_sha256(receipt_hash, "gateway receipt hash")
        _require_sha256(envelope_hash, "signed gateway envelope hash")
        _require_sha256(commitment_hash, "request commitment hash")
        _require_sha256(attestation_hash, "verified gateway attestation hash")
        _parse_canonical_utc(observed_at_utc)
        replay_key = _replay_key(signer_fingerprint, nonce)
        entry_values: dict[str, Any] = {
            "schema_version": "adaptive-transport-gateway-local-antireplay-entry-v3",
            "replay_key": replay_key,
            "signer_fingerprint": signer_fingerprint,
            "nonce": nonce,
            "receipt_hash": receipt_hash,
            "envelope_hash": envelope_hash,
            "commitment_hash": commitment_hash,
            "attestation_hash": attestation_hash,
            "observed_at_utc": observed_at_utc,
        }
        entry = TransportGatewayReplayLedgerEntry.model_validate(
            _addressed(entry_values, "entry_hash")
        )
        payload = (canonical_json(entry) + "\n").encode("utf-8")
        path = self._root / f"{replay_key}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise AdaptiveTransportGatewayError(
                "transport gateway nonce has already been observed"
            ) from exc
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            # A partial create remains as a fail-closed tombstone.  Reusing the
            # nonce after a storage failure would be less safe than blocking it.
            raise
        return replay_key

    def load_entry(
        self,
        *,
        signer_fingerprint: Sha256,
        nonce: str,
    ) -> TransportGatewayReplayLedgerEntry:
        """Read and strictly validate one previously consumed nonce entry."""

        _require_sha256(signer_fingerprint, "gateway signer fingerprint")
        _require_nonce(nonce)
        replay_key = _replay_key(signer_fingerprint, nonce)
        path = self._root / f"{replay_key}.json"
        if path.is_symlink() or not path.is_file():
            raise AdaptiveTransportGatewayError(
                "transport gateway anti-replay entry is missing or indirect"
            )
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise AdaptiveTransportGatewayError(
                "transport gateway anti-replay entry is missing"
            ) from exc
        try:
            entry = TransportGatewayReplayLedgerEntry.model_validate_json(payload)
        except Exception as exc:
            raise AdaptiveTransportGatewayError(
                "transport gateway anti-replay entry is invalid"
            ) from exc
        if payload != (canonical_json(entry) + "\n").encode("utf-8"):
            raise AdaptiveTransportGatewayError(
                "transport gateway anti-replay entry is not canonical"
            )
        if entry.replay_key != replay_key:
            raise AdaptiveTransportGatewayError(
                "transport gateway anti-replay entry belongs to another nonce"
            )
        return entry


class TransportGatewayRequestNonceLedger:
    """Gateway-owned create-once ledger reserved before any network attempt."""

    def __init__(self, root: Path) -> None:
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise AdaptiveTransportGatewayError(
                "gateway request nonce ledger root must be a real directory"
            )
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise AdaptiveTransportGatewayError(
                "gateway request nonce ledger root must not be a symlink"
            )
        self._root = root.resolve(strict=True)

    @property
    def root(self) -> Path:
        return self._root

    def reserve_once(
        self,
        commitment: AdaptiveTransportRequestCommitment,
        *,
        reserved_at_utc: datetime,
    ) -> str:
        """Reserve a request nonce atomically before DNS or connection setup."""

        if not isinstance(commitment, AdaptiveTransportRequestCommitment):
            raise AdaptiveTransportGatewayError(
                "gateway nonce reservation needs a typed request commitment"
            )
        validate_transport_gateway_request_freshness(
            commitment,
            now_utc=reserved_at_utc,
        )
        reservation_key = hashlib.sha256(
            b"autoresearch-adaptive-transport-gateway-request-nonce-v1\n"
            + commitment.nonce.encode("ascii")
        ).hexdigest()
        reserved_at_text = _format_canonical_utc(reserved_at_utc)
        entry = {
            "schema_version": "adaptive-transport-gateway-request-nonce-entry-v1",
            "reservation_key": reservation_key,
            "nonce": commitment.nonce,
            "request_id": commitment.request_id,
            "commitment_hash": commitment.commitment_hash,
            "reserved_at_utc": reserved_at_text,
        }
        payload = (canonical_json(entry) + "\n").encode("utf-8")
        path = self._root / f"{reservation_key}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise AdaptiveTransportGatewayError(
                "transport gateway request nonce was already reserved"
            ) from exc
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return reservation_key


def build_transport_gateway_request_commitment(
    *,
    request_bytes: bytes,
    request_id: str,
    provider_name: str,
    model_name: str,
    request_url: str,
    allowlisted_origins: Collection[str],
    nonce: str,
    issued_at_utc: str,
    cell_id: str,
    trajectory_id: str,
    reservation_id: str,
    reservation_hash: str,
    pre_call_id: str,
    pre_call_hash: str,
    max_redirects: int = 0,
) -> AdaptiveTransportRequestCommitment:
    """Build a pre-transport commitment from the exact bytes sent to the gateway."""

    if not isinstance(request_bytes, bytes):
        raise AdaptiveTransportGatewayError("gateway request payload must be exact bytes")
    _require_request_id(request_id)
    _require_nonce(nonce)
    _parse_canonical_utc(issued_at_utc)
    canonical_url = _canonical_public_https_url(request_url)
    if canonical_url != request_url:
        raise AdaptiveTransportGatewayError("gateway request URL is not canonical")
    origin = _origin_from_url(canonical_url)
    _require_origin_allowlisted(origin, allowlisted_origins)
    request_messages_sha256 = _request_messages_sha256(request_bytes, model_name)
    values: dict[str, Any] = {
        "schema_version": "adaptive-transport-request-commitment-v1",
        "request_id": request_id,
        "provider_name": provider_name,
        "model_name": model_name,
        "request_method": "POST",
        "request_url": canonical_url,
        "request_origin": origin,
        "request_payload_sha256": _sha256_bytes(request_bytes),
        "request_payload_size_bytes": len(request_bytes),
        "request_messages_sha256": request_messages_sha256,
        "nonce": nonce,
        "issued_at_utc": issued_at_utc,
        "cell_id": cell_id,
        "trajectory_id": trajectory_id,
        "reservation_id": reservation_id,
        "reservation_hash": reservation_hash,
        "pre_call_id": pre_call_id,
        "pre_call_hash": pre_call_hash,
        "max_redirects": max_redirects,
    }
    return AdaptiveTransportRequestCommitment.model_validate(_addressed(values, "commitment_hash"))


def build_adaptive_transport_gateway_receipt(
    *,
    gateway_receipt_id: str,
    request_commitment: AdaptiveTransportRequestCommitment,
    transmitted_request_bytes: bytes,
    completed_at_utc: str,
    final_url: str,
    http_status_code: int,
    connected_ip: str,
    tls_protocol: Literal["TLSv1.2", "TLSv1.3"],
    response_body: bytes,
    gateway_build_sha256: str,
    gateway_source_sha256: str,
    redirect_chain: tuple[AdaptiveTransportRedirectHop, ...] = (),
    tls_peer_certificate_sha256: str | None = None,
    tls_peer_spki_sha256: str | None = None,
) -> AdaptiveTransportGatewayReceipt:
    """Construct the canonical payload an external gateway must sign.

    This function performs no transport and grants no trust.  It is intentionally a
    pure receipt builder for a separately operated gateway process.
    """

    if not isinstance(transmitted_request_bytes, bytes) or not isinstance(response_body, bytes):
        raise AdaptiveTransportGatewayError("gateway receipt requires exact byte strings")
    (
        provider_response_id_sha256,
        provider_response_model,
        provider_response_model_utf8_sha256,
        provider_response_model_matches_committed_model,
        visible_output_sha256,
        reasoning_output_sha256,
        usage_sha256,
    ) = _response_projection_hashes(
        response_body,
        http_status_code=http_status_code,
        expected_model_name=request_commitment.model_name,
    )
    values: dict[str, Any] = {
        "schema_version": "adaptive-transport-gateway-receipt-v2",
        "gateway_receipt_id": gateway_receipt_id,
        "request_commitment": request_commitment.model_dump(mode="json"),
        "request_commitment_hash": request_commitment.commitment_hash,
        "transmitted_request_sha256": _sha256_bytes(transmitted_request_bytes),
        "transmitted_request_size_bytes": len(transmitted_request_bytes),
        "completed_at_utc": completed_at_utc,
        "final_url": final_url,
        "final_method": "POST",
        "http_status_code": http_status_code,
        "connected_ip": connected_ip,
        "tls_peer_certificate_sha256": tls_peer_certificate_sha256,
        "tls_peer_spki_sha256": tls_peer_spki_sha256,
        "tls_protocol": tls_protocol,
        "tls_chain_verified": True,
        "tls_hostname_verified": True,
        "redirect_chain": [hop.model_dump(mode="json") for hop in redirect_chain],
        "response_body_sha256": _sha256_bytes(response_body),
        "response_body_size_bytes": len(response_body),
        "provider_response_id_sha256": provider_response_id_sha256,
        "provider_response_model": provider_response_model,
        "provider_response_model_utf8_sha256": provider_response_model_utf8_sha256,
        "provider_response_model_matches_committed_model": (
            provider_response_model_matches_committed_model
        ),
        "completion_fields_available": visible_output_sha256 is not None,
        "visible_output_utf8_sha256": visible_output_sha256,
        "reasoning_output_utf8_sha256": reasoning_output_sha256,
        "usage_canonical_json_sha256": usage_sha256,
        "gateway_build_sha256": gateway_build_sha256,
        "gateway_source_sha256": gateway_source_sha256,
        "gateway_nonce_first_seen": True,
        "gateway_clock_checked": True,
        "complete_response_body_read": True,
    }
    return AdaptiveTransportGatewayReceipt.model_validate(_addressed(values, "receipt_hash"))


def extract_adaptive_transport_gateway_completion(
    *,
    response_body: bytes,
    http_status_code: int,
    expected_model_name: str,
) -> AdaptiveTransportGatewayCompletionPayload | None:
    """Parse one response only when its exact model matches the pre-call commitment."""

    if not isinstance(response_body, bytes):
        raise AdaptiveTransportGatewayError("gateway response payload must be exact bytes")
    if not 100 <= http_status_code <= 599:
        raise AdaptiveTransportGatewayError("gateway HTTP status is invalid")
    if not 200 <= http_status_code < 300:
        return None
    payload = _load_duplicate_free_json(
        response_body,
        label="gateway response body",
    )
    return _completion_payload_from_json(
        payload,
        expected_model_name=expected_model_name,
    )


def build_adaptive_transport_gateway_failure_receipt(
    *,
    gateway_receipt_id: str,
    request_commitment: AdaptiveTransportRequestCommitment,
    observed_request_bytes: bytes,
    failed_at_utc: str,
    failure_stage: Literal[
        "dns_resolution",
        "tcp_connect",
        "tls_handshake",
        "request_write",
        "response_headers",
    ],
    attempted_url: str,
    error_type: str,
    error_message: str,
    gateway_build_sha256: str,
    gateway_source_sha256: str,
    redirect_chain: tuple[AdaptiveTransportRedirectHop, ...] = (),
    connected_ip: str | None = None,
    tls_peer_certificate_sha256: str | None = None,
    tls_peer_spki_sha256: str | None = None,
) -> AdaptiveTransportGatewayFailureReceipt:
    """Build a signable gateway failure without retaining exception text."""

    if not isinstance(observed_request_bytes, bytes):
        raise AdaptiveTransportGatewayError("gateway failure receipt requires exact request bytes")
    if not error_type or not error_message:
        raise AdaptiveTransportGatewayError(
            "gateway failure receipt needs non-empty error metadata"
        )
    values: dict[str, Any] = {
        "schema_version": "adaptive-transport-gateway-failure-receipt-v1",
        "gateway_receipt_id": gateway_receipt_id,
        "request_commitment": request_commitment.model_dump(mode="json"),
        "request_commitment_hash": request_commitment.commitment_hash,
        "observed_request_sha256": _sha256_bytes(observed_request_bytes),
        "observed_request_size_bytes": len(observed_request_bytes),
        "failed_at_utc": failed_at_utc,
        "failure_stage": failure_stage,
        "attempted_url": attempted_url,
        "attempted_method": "POST",
        "connected_ip": connected_ip,
        "tls_peer_certificate_sha256": tls_peer_certificate_sha256,
        "tls_peer_spki_sha256": tls_peer_spki_sha256,
        "redirect_chain": [hop.model_dump(mode="json") for hop in redirect_chain],
        "failure_error_type_sha256": _sha256_bytes(error_type.encode("utf-8")),
        "failure_error_message_sha256": _sha256_bytes(error_message.encode("utf-8")),
        "gateway_build_sha256": gateway_build_sha256,
        "gateway_source_sha256": gateway_source_sha256,
        "gateway_nonce_first_seen": True,
        "gateway_clock_checked": True,
        "http_response_received": False,
        "completion_fields_available": False,
    }
    return AdaptiveTransportGatewayFailureReceipt.model_validate(_addressed(values, "receipt_hash"))


def build_signed_adaptive_transport_gateway_receipt(
    *,
    receipt: AdaptiveTransportGatewayReceiptEvidence,
    gateway_public_key_pem: str,
    signature_base64: str,
) -> SignedAdaptiveTransportGatewayReceipt:
    """Wrap an externally produced signature without treating its key as trusted."""

    _, embedded_fingerprint = _load_canonical_ed25519_public_key(gateway_public_key_pem)
    values: dict[str, Any] = {
        "schema_version": "signed-adaptive-transport-gateway-receipt-v1",
        "receipt": receipt.model_dump(mode="json"),
        "signature_algorithm": "Ed25519",
        "signature_domain": _SIGNATURE_DOMAIN_LABEL,
        "gateway_public_key_pem": gateway_public_key_pem,
        "embedded_gateway_public_key_sha256_untrusted": embedded_fingerprint,
        "signature_base64": signature_base64,
    }
    return SignedAdaptiveTransportGatewayReceipt.model_validate(_addressed(values, "envelope_hash"))


def transport_gateway_receipt_signature_message(
    receipt: AdaptiveTransportGatewayReceiptEvidence,
) -> bytes:
    """Return the exact domain-separated bytes the external gateway must sign."""

    if not isinstance(
        receipt,
        AdaptiveTransportGatewayReceipt | AdaptiveTransportGatewayFailureReceipt,
    ):
        raise AdaptiveTransportGatewayError(
            "only an adaptive transport gateway receipt can be signed"
        )
    return _SIGNATURE_DOMAIN + canonical_json(receipt).encode("utf-8")


def verify_adaptive_transport_gateway_receipt(
    signed_receipt: SignedAdaptiveTransportGatewayReceipt,
    *,
    expected_request_commitment: AdaptiveTransportRequestCommitment,
    trusted_public_key_sha256: str,
    trusted_gateway_build_sha256: str,
    trusted_gateway_source_sha256: str,
    allowlisted_origins: Collection[str],
    now_utc: datetime,
    replay_ledger: TransportGatewayReplayLedger,
) -> VerifiedAdaptiveTransportGatewayAttestation:
    """Verify and consume one signed receipt against external trust policy.

    All trust anchors are mandatory arguments.  None is inferred from the signed
    artifact.  A successful call consumes the signer-scoped nonce atomically; an
    identical second call is therefore rejected rather than counted twice.
    """

    if not isinstance(signed_receipt, SignedAdaptiveTransportGatewayReceipt):
        raise AdaptiveTransportGatewayError(
            "process-local traces and unsigned artifacts cannot become formal evidence"
        )
    if not isinstance(expected_request_commitment, AdaptiveTransportRequestCommitment):
        raise AdaptiveTransportGatewayError("expected request commitment is missing")
    if not isinstance(replay_ledger, TransportGatewayReplayLedger):
        raise AdaptiveTransportGatewayError("a persistent verifier replay ledger is required")
    _require_sha256(trusted_public_key_sha256, "trusted gateway public-key fingerprint")
    _require_sha256(trusted_gateway_build_sha256, "trusted gateway build hash")
    _require_sha256(trusted_gateway_source_sha256, "trusted gateway source hash")
    verified_at = _require_aware_utc(now_utc)
    receipt = signed_receipt.receipt
    if not hmac.compare_digest(
        canonical_json(receipt.request_commitment),
        canonical_json(expected_request_commitment),
    ):
        raise AdaptiveTransportGatewayError(
            "signed gateway receipt does not match the expected request or lineage"
        )
    _require_origin_allowlisted(receipt.request_commitment.request_origin, allowlisted_origins)
    for hop in receipt.redirect_chain:
        _require_origin_allowlisted(_origin_from_url(hop.source_url), allowlisted_origins)
        _require_origin_allowlisted(_origin_from_url(hop.target_url), allowlisted_origins)
    terminal_url = (
        receipt.final_url
        if isinstance(receipt, AdaptiveTransportGatewayReceipt)
        else receipt.attempted_url
    )
    _require_origin_allowlisted(_origin_from_url(terminal_url), allowlisted_origins)
    if not hmac.compare_digest(receipt.gateway_build_sha256, trusted_gateway_build_sha256):
        raise AdaptiveTransportGatewayError("gateway build does not match external policy")
    if not hmac.compare_digest(receipt.gateway_source_sha256, trusted_gateway_source_sha256):
        raise AdaptiveTransportGatewayError("gateway source does not match external policy")
    public_key, actual_fingerprint = _load_canonical_ed25519_public_key(
        signed_receipt.gateway_public_key_pem
    )
    if not hmac.compare_digest(actual_fingerprint, trusted_public_key_sha256):
        raise AdaptiveTransportGatewayError(
            "gateway signer key does not match the external trust anchor"
        )
    signature = _decode_canonical_signature(signed_receipt.signature_base64)
    try:
        public_key.verify(signature, transport_gateway_receipt_signature_message(receipt))
    except InvalidSignature as exc:
        raise AdaptiveTransportGatewayError(
            "detached transport gateway signature verification failed"
        ) from exc
    _verify_freshness(receipt, verified_at)
    verified_at_text = _format_canonical_utc(verified_at)
    attestation_values: dict[str, Any] = {
        "schema_version": "verified-adaptive-transport-gateway-attestation-v1",
        "receipt_hash": receipt.receipt_hash,
        "envelope_hash": signed_receipt.envelope_hash,
        "request_commitment_hash": expected_request_commitment.commitment_hash,
        "trusted_gateway_public_key_sha256": actual_fingerprint,
        "trusted_gateway_build_sha256": receipt.gateway_build_sha256,
        "trusted_gateway_source_sha256": receipt.gateway_source_sha256,
        "verified_at_utc": verified_at_text,
        "outcome": (
            "http_response"
            if isinstance(receipt, AdaptiveTransportGatewayReceipt)
            else "transport_failure"
        ),
        "http_response_received": isinstance(receipt, AdaptiveTransportGatewayReceipt),
        "provider_completion_eligible": (
            isinstance(receipt, AdaptiveTransportGatewayReceipt)
            and receipt.completion_fields_available
        ),
        "signature_verified": True,
        "request_bytes_and_lineage_verified": True,
        "https_origin_policy_verified": True,
        "tls_peer_binding_verified": True,
        "nonce_accepted_once": True,
        "independent_external_gateway_verified": True,
        "process_local_client_trace_promoted": False,
        "formal_transport_eligible": True,
    }
    attestation = VerifiedAdaptiveTransportGatewayAttestation.model_validate(
        _addressed(attestation_values, "attestation_hash")
    )
    replay_ledger.consume_once(
        signer_fingerprint=actual_fingerprint,
        nonce=expected_request_commitment.nonce,
        receipt_hash=receipt.receipt_hash,
        envelope_hash=signed_receipt.envelope_hash,
        commitment_hash=expected_request_commitment.commitment_hash,
        attestation_hash=attestation.attestation_hash,
        observed_at_utc=verified_at_text,
    )
    return attestation


def replay_verify_adaptive_transport_gateway_attestation(
    signed_receipt: SignedAdaptiveTransportGatewayReceipt,
    *,
    expected_request_commitment: AdaptiveTransportRequestCommitment,
    accepted_attestation: VerifiedAdaptiveTransportGatewayAttestation,
    trusted_public_key_sha256: str,
    trusted_gateway_build_sha256: str,
    trusted_gateway_source_sha256: str,
    allowlisted_origins: Collection[str],
    replay_ledger: TransportGatewayReplayLedger,
) -> PostRunAdaptiveTransportGatewayReplay:
    """Reverify prior signed evidence without current-time freshness or nonce reuse.

    This terminal-audit path does not trust the attestation's self hash alone.  It
    rechecks the gateway signature and every external policy binding, replays
    freshness at the original verification time, and checks the local create-once
    anti-replay entry written by the immediate verifier.  That local entry is not an
    independent acceptance signer; the externally anchored gateway signature is the
    formal transport evidence.
    """

    if not isinstance(signed_receipt, SignedAdaptiveTransportGatewayReceipt):
        raise AdaptiveTransportGatewayError("post-run replay requires a signed gateway receipt")
    if not isinstance(expected_request_commitment, AdaptiveTransportRequestCommitment):
        raise AdaptiveTransportGatewayError(
            "post-run replay requires the expected request commitment"
        )
    if not isinstance(accepted_attestation, VerifiedAdaptiveTransportGatewayAttestation):
        raise AdaptiveTransportGatewayError(
            "post-run replay requires the original verified attestation"
        )
    if not isinstance(replay_ledger, TransportGatewayReplayLedger):
        raise AdaptiveTransportGatewayError(
            "post-run replay requires the verifier-owned replay ledger"
        )
    _require_sha256(trusted_public_key_sha256, "trusted gateway public-key fingerprint")
    _require_sha256(trusted_gateway_build_sha256, "trusted gateway build hash")
    _require_sha256(trusted_gateway_source_sha256, "trusted gateway source hash")
    receipt = signed_receipt.receipt
    if not hmac.compare_digest(
        canonical_json(receipt.request_commitment),
        canonical_json(expected_request_commitment),
    ):
        raise AdaptiveTransportGatewayError(
            "post-run gateway receipt does not match the expected request or lineage"
        )
    _require_origin_allowlisted(receipt.request_commitment.request_origin, allowlisted_origins)
    for hop in receipt.redirect_chain:
        _require_origin_allowlisted(_origin_from_url(hop.source_url), allowlisted_origins)
        _require_origin_allowlisted(_origin_from_url(hop.target_url), allowlisted_origins)
    terminal_url = (
        receipt.final_url
        if isinstance(receipt, AdaptiveTransportGatewayReceipt)
        else receipt.attempted_url
    )
    _require_origin_allowlisted(_origin_from_url(terminal_url), allowlisted_origins)
    if not hmac.compare_digest(receipt.gateway_build_sha256, trusted_gateway_build_sha256):
        raise AdaptiveTransportGatewayError("post-run gateway build does not match external policy")
    if not hmac.compare_digest(receipt.gateway_source_sha256, trusted_gateway_source_sha256):
        raise AdaptiveTransportGatewayError(
            "post-run gateway source does not match external policy"
        )
    public_key, actual_fingerprint = _load_canonical_ed25519_public_key(
        signed_receipt.gateway_public_key_pem
    )
    if not hmac.compare_digest(actual_fingerprint, trusted_public_key_sha256):
        raise AdaptiveTransportGatewayError(
            "post-run gateway signer does not match the external trust anchor"
        )
    try:
        public_key.verify(
            _decode_canonical_signature(signed_receipt.signature_base64),
            transport_gateway_receipt_signature_message(receipt),
        )
    except InvalidSignature as exc:
        raise AdaptiveTransportGatewayError(
            "post-run transport gateway signature verification failed"
        ) from exc
    original_accepted_at = _parse_canonical_utc(accepted_attestation.verified_at_utc)
    _verify_freshness(receipt, original_accepted_at)
    expected_outcome = (
        "http_response"
        if isinstance(receipt, AdaptiveTransportGatewayReceipt)
        else "transport_failure"
    )
    expected_http_response = isinstance(receipt, AdaptiveTransportGatewayReceipt)
    expected_completion = (
        expected_http_response
        and isinstance(receipt, AdaptiveTransportGatewayReceipt)
        and receipt.completion_fields_available
    )
    if (
        accepted_attestation.receipt_hash,
        accepted_attestation.envelope_hash,
        accepted_attestation.request_commitment_hash,
        accepted_attestation.trusted_gateway_public_key_sha256,
        accepted_attestation.trusted_gateway_build_sha256,
        accepted_attestation.trusted_gateway_source_sha256,
        accepted_attestation.outcome,
        accepted_attestation.http_response_received,
        accepted_attestation.provider_completion_eligible,
    ) != (
        receipt.receipt_hash,
        signed_receipt.envelope_hash,
        expected_request_commitment.commitment_hash,
        actual_fingerprint,
        trusted_gateway_build_sha256,
        trusted_gateway_source_sha256,
        expected_outcome,
        expected_http_response,
        expected_completion,
    ):
        raise AdaptiveTransportGatewayError(
            "original gateway attestation does not replay from signed evidence"
        )
    local_entry = replay_ledger.load_entry(
        signer_fingerprint=actual_fingerprint,
        nonce=expected_request_commitment.nonce,
    )
    if (
        local_entry.receipt_hash,
        local_entry.envelope_hash,
        local_entry.commitment_hash,
        local_entry.attestation_hash,
        local_entry.observed_at_utc,
    ) != (
        receipt.receipt_hash,
        signed_receipt.envelope_hash,
        expected_request_commitment.commitment_hash,
        accepted_attestation.attestation_hash,
        accepted_attestation.verified_at_utc,
    ):
        raise AdaptiveTransportGatewayError(
            "local anti-replay entry disagrees with original signed evidence"
        )
    replay_values: dict[str, Any] = {
        "schema_version": "post-run-adaptive-transport-gateway-replay-v2",
        "receipt_hash": receipt.receipt_hash,
        "envelope_hash": signed_receipt.envelope_hash,
        "request_commitment_hash": expected_request_commitment.commitment_hash,
        "accepted_attestation_hash": accepted_attestation.attestation_hash,
        "local_antireplay_entry_hash": local_entry.entry_hash,
        "original_accepted_at_utc": accepted_attestation.verified_at_utc,
        "signature_and_external_policy_reverified": True,
        "original_freshness_replayed": True,
        "local_antireplay_integrity_replayed": True,
        "local_ledger_is_independent_acceptance_evidence": False,
        "nonce_was_not_reconsumed": True,
        "formal_transport_eligible": True,
        "provider_completion_eligible": expected_completion,
    }
    return PostRunAdaptiveTransportGatewayReplay.model_validate(
        _addressed(replay_values, "replay_hash")
    )


def load_signed_adaptive_transport_gateway_receipt(
    payload: bytes,
) -> SignedAdaptiveTransportGatewayReceipt:
    """Load exact canonical JSON bytes; old traces and whitespace variants fail."""

    if not isinstance(payload, bytes):
        raise AdaptiveTransportGatewayError("signed gateway artifact must be bytes")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdaptiveTransportGatewayError(
            "signed gateway artifact is not canonical UTF-8 JSON"
        ) from exc
    try:
        loaded = SignedAdaptiveTransportGatewayReceipt.model_validate_json(text)
    except Exception as exc:
        raise AdaptiveTransportGatewayError(
            "signed gateway artifact does not match the v1 signed schema"
        ) from exc
    if payload != canonical_json(loaded).encode("utf-8"):
        raise AdaptiveTransportGatewayError(
            "signed gateway artifact has non-canonical or trailing bytes"
        )
    return loaded


def validate_transport_gateway_request_freshness(
    commitment: AdaptiveTransportRequestCommitment,
    *,
    now_utc: datetime,
) -> None:
    """Fail before network when the controller commitment is stale or future-dated."""

    if not isinstance(commitment, AdaptiveTransportRequestCommitment):
        raise AdaptiveTransportGatewayError("typed gateway request commitment is required")
    verified_at = _require_aware_utc(now_utc)
    issued_at = _parse_canonical_utc(commitment.issued_at_utc)
    if issued_at > verified_at + _MAX_FUTURE_SKEW:
        raise AdaptiveTransportGatewayError("gateway request commitment is from the future")
    if issued_at < verified_at - _MAX_RECEIPT_AGE:
        raise AdaptiveTransportGatewayError("gateway request commitment is stale")


def _verify_freshness(
    receipt: AdaptiveTransportGatewayReceiptEvidence,
    now_utc: datetime,
) -> None:
    issued_at = _parse_canonical_utc(receipt.request_commitment.issued_at_utc)
    terminal_at = _parse_canonical_utc(
        receipt.completed_at_utc
        if isinstance(receipt, AdaptiveTransportGatewayReceipt)
        else receipt.failed_at_utc
    )
    if issued_at > now_utc + _MAX_FUTURE_SKEW:
        raise AdaptiveTransportGatewayError("gateway request commitment is from the future")
    if terminal_at > now_utc + _MAX_FUTURE_SKEW:
        raise AdaptiveTransportGatewayError("gateway receipt is from the future")
    if issued_at < now_utc - _MAX_RECEIPT_AGE:
        raise AdaptiveTransportGatewayError("gateway request commitment is stale")
    if terminal_at < now_utc - _MAX_RECEIPT_AGE:
        raise AdaptiveTransportGatewayError("gateway receipt is stale")


def _load_canonical_ed25519_public_key(
    public_key_pem: str,
) -> tuple[Ed25519PublicKey, str]:
    if not public_key_pem:
        raise AdaptiveTransportGatewayError("gateway public key is empty")
    try:
        loaded = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise AdaptiveTransportGatewayError("gateway public key is not valid ASCII PEM") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise AdaptiveTransportGatewayError("gateway public key must use Ed25519")
    canonical_pem = loaded.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    if public_key_pem != canonical_pem:
        raise AdaptiveTransportGatewayError(
            "gateway public key must be one canonical Ed25519 SPKI PEM block"
        )
    der = loaded.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return loaded, _sha256_bytes(der)


def _decode_canonical_signature(signature_base64: str) -> bytes:
    try:
        signature = base64.b64decode(signature_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AdaptiveTransportGatewayError(
            "transport gateway signature is not canonical base64"
        ) from exc
    if len(signature) != 64:
        raise AdaptiveTransportGatewayError("Ed25519 gateway signature must be 64 bytes")
    if base64.b64encode(signature).decode("ascii") != signature_base64:
        raise AdaptiveTransportGatewayError(
            "transport gateway signature base64 has non-canonical pad bits"
        )
    return signature


def _canonical_public_https_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AdaptiveTransportGatewayError("gateway origin must use public HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise AdaptiveTransportGatewayError("gateway origin must not contain userinfo")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise AdaptiveTransportGatewayError("gateway origin must not contain path/query/fragment")
    host = _canonical_public_host(parsed.hostname)
    port = _validated_port(parsed)
    if port == 443:
        raise AdaptiveTransportGatewayError("default HTTPS port must be omitted")
    netloc = _format_netloc(host, port)
    canonical = f"https://{netloc}"
    if value != canonical:
        raise AdaptiveTransportGatewayError("gateway origin is not canonical")
    return canonical


def _canonical_public_https_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AdaptiveTransportGatewayError("gateway URL must use public HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise AdaptiveTransportGatewayError("gateway URL must not contain userinfo")
    if parsed.query or parsed.fragment:
        raise AdaptiveTransportGatewayError("gateway URL must not contain query or fragment")
    host = _canonical_public_host(parsed.hostname)
    port = _validated_port(parsed)
    if port == 443:
        raise AdaptiveTransportGatewayError("default HTTPS port must be omitted")
    path = parsed.path or "/"
    if not path.startswith("/") or "%" in path or "\\" in path:
        raise AdaptiveTransportGatewayError("gateway URL path must be an unescaped absolute path")
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in path):
        raise AdaptiveTransportGatewayError("gateway URL path must use visible ASCII")
    canonical = urllib.parse.urlunsplit(("https", _format_netloc(host, port), path, "", ""))
    if value != canonical:
        raise AdaptiveTransportGatewayError("gateway URL is not canonical")
    return canonical


def _canonical_public_host(value: str) -> str:
    if value != value.casefold() or value.endswith("."):
        raise AdaptiveTransportGatewayError("gateway host must be lowercase and unambiguous")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AdaptiveTransportGatewayError("gateway host must use canonical ASCII") from exc
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        normalized = value.casefold()
        if (
            "." not in normalized
            or normalized == "localhost"
            or normalized.endswith((".localhost", ".local", ".internal", ".lan", ".home"))
        ):
            raise AdaptiveTransportGatewayError(
                "gateway host is local or not fully qualified"
            ) from None
        labels = normalized.split(".")
        if len(normalized) > 253 or any(
            not _HOST_LABEL_PATTERN.fullmatch(label) for label in labels
        ):
            raise AdaptiveTransportGatewayError(
                "gateway host is not canonical DNS syntax"
            ) from None
        return normalized
    if not address.is_global:
        raise AdaptiveTransportGatewayError("gateway IP literal is not globally routable")
    canonical_ip = address.compressed
    if value != canonical_ip:
        raise AdaptiveTransportGatewayError("gateway IP literal is not canonical")
    return canonical_ip


def _require_global_ip(value: str) -> None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("gateway connected IP is invalid") from exc
    if value != address.compressed:
        raise ValueError("gateway connected IP is not canonical")
    if not address.is_global:
        raise ValueError("gateway connected IP is not globally routable")


def _validated_port(parsed: urllib.parse.SplitResult) -> int | None:
    try:
        port = parsed.port
    except ValueError as exc:
        raise AdaptiveTransportGatewayError("gateway URL contains an invalid port") from exc
    if port is not None and not 1 <= port <= 65_535:
        raise AdaptiveTransportGatewayError("gateway URL port is out of range")
    return port


def _format_netloc(host: str, port: int | None) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    return f"{rendered_host}:{port}" if port is not None else rendered_host


def _origin_from_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    host = _canonical_public_host(parsed.hostname or "")
    port = _validated_port(parsed)
    return f"https://{_format_netloc(host, port)}"


def _require_origin_allowlisted(origin: str, allowlisted_origins: Collection[str]) -> None:
    if isinstance(allowlisted_origins, str | bytes) or not allowlisted_origins:
        raise AdaptiveTransportGatewayError("external HTTPS origin allowlist is required")
    canonical_origins: set[str] = set()
    for candidate in allowlisted_origins:
        if not isinstance(candidate, str):
            raise AdaptiveTransportGatewayError("origin allowlist contains a non-string value")
        canonical_origins.add(_canonical_public_https_origin(candidate))
    if origin not in canonical_origins:
        raise AdaptiveTransportGatewayError("gateway origin is not externally allowlisted")


def _load_duplicate_free_json(payload_bytes: bytes, *, label: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key is forbidden: {key}")
            result[key] = value
        return result

    try:
        decoded = payload_bytes.decode("utf-8")
        payload = json.loads(
            decoded,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AdaptiveTransportGatewayError(f"{label} must be duplicate-free UTF-8 JSON") from exc
    return payload


def _request_messages_sha256(request_bytes: bytes, model_name: str) -> str:
    payload = _load_duplicate_free_json(request_bytes, label="gateway request bytes")
    if not isinstance(payload, dict) or payload.get("model") != model_name:
        raise AdaptiveTransportGatewayError(
            "gateway request body model does not match the committed model"
        )
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise AdaptiveTransportGatewayError("gateway request body needs a non-empty messages array")
    return canonical_sha256(messages)


def _response_projection_hashes(
    response_body: bytes,
    *,
    http_status_code: int,
    expected_model_name: str,
) -> tuple[
    str | None,
    str | None,
    str | None,
    bool,
    str | None,
    str | None,
    str | None,
]:
    try:
        payload = _load_duplicate_free_json(
            response_body,
            label="gateway response body",
        )
    except AdaptiveTransportGatewayError:
        if 200 <= http_status_code < 300:
            raise
        return None, None, None, False, None, None, None
    provider_response_id_hash: str | None = None
    provider_response_model: str | None = None
    provider_response_model_hash: str | None = None
    provider_response_model_matches = False
    if isinstance(payload, dict):
        provider_response_id = payload.get("id")
        if isinstance(provider_response_id, str) and provider_response_id:
            provider_response_id_hash = _sha256_bytes(provider_response_id.encode("utf-8"))
        response_model_value = payload.get("model")
        if isinstance(response_model_value, str) and response_model_value:
            provider_response_model = response_model_value
            provider_response_model_hash = _sha256_bytes(response_model_value.encode("utf-8"))
            provider_response_model_matches = hmac.compare_digest(
                response_model_value,
                expected_model_name,
            )
    if not 200 <= http_status_code < 300:
        return (
            provider_response_id_hash,
            provider_response_model,
            provider_response_model_hash,
            provider_response_model_matches,
            None,
            None,
            None,
        )
    completion = _completion_payload_from_json(
        payload,
        expected_model_name=expected_model_name,
    )
    return (
        provider_response_id_hash,
        completion.provider_response_model,
        completion.provider_response_model_utf8_sha256,
        True,
        completion.visible_output_utf8_sha256,
        completion.reasoning_output_utf8_sha256,
        completion.usage_canonical_json_sha256,
    )


def _completion_payload_from_json(
    payload: Any,
    *,
    expected_model_name: str,
) -> AdaptiveTransportGatewayCompletionPayload:
    if not isinstance(payload, dict):
        raise AdaptiveTransportGatewayError("gateway success response must be a JSON object")
    response_model = payload.get("model")
    if not isinstance(response_model, str) or not response_model:
        raise AdaptiveTransportGatewayError(
            "gateway success response lacks a non-empty provider model"
        )
    if not hmac.compare_digest(response_model, expected_model_name):
        raise AdaptiveTransportGatewayError(
            "gateway success response model does not exactly match the committed model"
        )
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AdaptiveTransportGatewayError(
            "gateway success response lacks the first completion choice"
        )
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AdaptiveTransportGatewayError("gateway success response lacks a message object")
    visible = message.get("content")
    reasoning_value = message.get("reasoning_content")
    usage = payload.get("usage", {})
    if not isinstance(visible, str) or not visible.strip():
        raise AdaptiveTransportGatewayError(
            "gateway success response contains empty/non-text visible output"
        )
    if not isinstance(usage, dict):
        raise AdaptiveTransportGatewayError("gateway success response usage must be an object")
    visible_output = visible.strip()
    reasoning_output = (
        reasoning_value[:200_000]
        if isinstance(reasoning_value, str) and reasoning_value.strip()
        else ""
    )
    values: dict[str, Any] = {
        "schema_version": "adaptive-transport-gateway-completion-payload-v2",
        "provider_response_model": response_model,
        "provider_response_model_utf8_sha256": _sha256_bytes(response_model.encode("utf-8")),
        "visible_output": visible_output,
        "reasoning_output": reasoning_output,
        "usage": usage,
        "visible_output_utf8_sha256": _sha256_bytes(visible_output.encode("utf-8")),
        "reasoning_output_utf8_sha256": _sha256_bytes(reasoning_output.encode("utf-8")),
        "usage_canonical_json_sha256": canonical_sha256(usage),
    }
    return AdaptiveTransportGatewayCompletionPayload.model_validate(
        _addressed(values, "completion_payload_hash")
    )


def _parse_canonical_utc(value: str) -> datetime:
    if not _UTC_SECONDS_PATTERN.fullmatch(value):
        raise AdaptiveTransportGatewayError("gateway timestamp is not canonical UTC seconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AdaptiveTransportGatewayError("gateway timestamp is invalid") from exc
    if _format_canonical_utc(parsed) != value:
        raise AdaptiveTransportGatewayError("gateway timestamp is not canonical")
    return parsed


def _format_canonical_utc(value: datetime) -> str:
    canonical = _require_aware_utc(value)
    if canonical.microsecond != 0:
        raise AdaptiveTransportGatewayError(
            "trusted verifier time must have whole-second precision"
        )
    return canonical.strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AdaptiveTransportGatewayError("trusted verifier clock must be timezone-aware")
    canonical = value.astimezone(timezone.utc)
    if value.utcoffset() != timedelta(0):
        raise AdaptiveTransportGatewayError("trusted verifier clock must be expressed in UTC")
    return canonical


def _require_request_id(value: str) -> None:
    if not _REQUEST_ID_PATTERN.fullmatch(value):
        raise AdaptiveTransportGatewayError("gateway request ID is not canonical")


def _require_nonce(value: str) -> None:
    if not _NONCE_PATTERN.fullmatch(value):
        raise AdaptiveTransportGatewayError(
            "gateway nonce must be 128-256 bits of lowercase hexadecimal"
        )


def _require_sha256(value: str, label: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AdaptiveTransportGatewayError(f"{label} must be a lowercase SHA-256 digest")


def _replay_key(signer_fingerprint: str, nonce: str) -> str:
    return hashlib.sha256(
        _REPLAY_ENTRY_DOMAIN + signer_fingerprint.encode("ascii") + b"\n" + nonce.encode("ascii")
    ).hexdigest()


def _calculated_hash(contract: KernelContract, hash_field: str) -> str:
    return canonical_sha256(contract.model_dump(mode="json", exclude={hash_field}))


def _addressed(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    normalized = dict(payload)
    normalized[hash_field] = canonical_sha256(normalized)
    return normalized


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
