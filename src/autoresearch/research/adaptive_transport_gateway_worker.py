"""One-shot independent HTTPS worker for signed adaptive transport receipts.

This module is intended to run as a separate process with a separately provisioned
Ed25519 private key.  It accepts one canonical request on stdin, reserves its nonce
before DNS/transport, performs one HTTPS POST with the system trust store, and emits
one canonical signed output on stdout.  A successful output contains only the
controller-visible text/reasoning/usage parsed from that same response plus its signed
receipt.  It never returns the request body, raw response body, API key, private key,
or provider response ID.

The research controller must not import this worker and call it in-process as formal
evidence.  It should invoke an independently launched process/service and verify the
result with :mod:`adaptive_transport_gateway` plus out-of-band pinned fingerprints.
The independently controlled launcher must also pin one durable nonce-ledger root;
allowing the research controller or each invocation to select a fresh root defeats
cross-process replay prevention.  The environment variable is deployment wiring,
not authority for an artifact-controlled runner to rotate that root.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import importlib.metadata
import ipaddress
import os
import platform
import socket
import ssl
import sys
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from pydantic import ConfigDict, Field, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    canonical_json,
    canonical_sha256,
)
from autoresearch.research.adaptive_transport_gateway import (
    AdaptiveTransportGatewayCompletionPayload,
    AdaptiveTransportGatewayError,
    AdaptiveTransportGatewayReceipt,
    AdaptiveTransportGatewayReceiptEvidence,
    AdaptiveTransportRequestCommitment,
    SignedAdaptiveTransportGatewayReceipt,
    TransportGatewayRequestNonceLedger,
    build_adaptive_transport_gateway_failure_receipt,
    build_adaptive_transport_gateway_receipt,
    build_signed_adaptive_transport_gateway_receipt,
    build_transport_gateway_request_commitment,
    extract_adaptive_transport_gateway_completion,
    transport_gateway_receipt_signature_message,
)

_PRIVATE_KEY_FD_ENV = "AUTORESEARCH_GATEWAY_PRIVATE_KEY_FD"
_PRIVATE_KEY_PEM_ENV = "AUTORESEARCH_GATEWAY_PRIVATE_KEY_PEM"
_API_KEY_ENV = "AUTORESEARCH_GATEWAY_PROVIDER_API_KEY"
_ORIGINS_ENV = "AUTORESEARCH_GATEWAY_ALLOWED_ORIGINS"
_PROVIDER_ENV = "AUTORESEARCH_GATEWAY_PROVIDER"
_MODEL_ENV = "AUTORESEARCH_GATEWAY_MODEL"
_NONCE_LEDGER_ENV = "AUTORESEARCH_GATEWAY_REQUEST_NONCE_LEDGER"
_TIMEOUT_ENV = "AUTORESEARCH_GATEWAY_TIMEOUT_SECONDS"
_MAX_STDIN_BYTES = 32 * 1024 * 1024
_MAX_PRIVATE_KEY_BYTES = 16 * 1024
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class AdaptiveTransportGatewayWorkerError(RuntimeError):
    """Raised when the independent worker cannot safely produce a receipt."""


class _FrozenWorkerContract(KernelContract):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdaptiveTransportGatewayWorkerRequest(_FrozenWorkerContract):
    """Secret-free canonical stdin contract for one gateway attempt."""

    schema_version: Literal["adaptive-transport-gateway-worker-request-v1"] = (
        "adaptive-transport-gateway-worker-request-v1"
    )
    request_commitment: AdaptiveTransportRequestCommitment
    request_payload_base64: str = Field(min_length=4, max_length=44_739_244)
    worker_request_hash: Sha256

    @model_validator(mode="after")
    def _validate_request(self) -> AdaptiveTransportGatewayWorkerRequest:
        request_bytes = self.request_bytes()
        if (
            hashlib.sha256(request_bytes).hexdigest(),
            len(request_bytes),
        ) != (
            self.request_commitment.request_payload_sha256,
            self.request_commitment.request_payload_size_bytes,
        ):
            raise ValueError("worker request bytes differ from the commitment")
        if self.worker_request_hash != canonical_sha256(
            self.model_dump(mode="json", exclude={"worker_request_hash"})
        ):
            raise ValueError("gateway worker request hash mismatch")
        return self

    def request_bytes(self) -> bytes:
        return _decode_canonical_base64(self.request_payload_base64)


class AdaptiveTransportGatewayWorkerTrustManifest(_FrozenWorkerContract):
    """Out-of-band values an operator pins before accepting worker receipts."""

    schema_version: Literal["adaptive-transport-gateway-worker-trust-manifest-v1"] = (
        "adaptive-transport-gateway-worker-trust-manifest-v1"
    )
    gateway_source_sha256: Sha256
    gateway_build_sha256: Sha256
    python_implementation: str = Field(min_length=1, max_length=64)
    python_version: str = Field(min_length=1, max_length=64)
    openssl_version: str = Field(min_length=1, max_length=256)
    cryptography_version: str = Field(min_length=1, max_length=64)
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> AdaptiveTransportGatewayWorkerTrustManifest:
        if self.manifest_hash != canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        ):
            raise ValueError("gateway worker trust manifest hash mismatch")
        return self


class AdaptiveTransportGatewayWorkerOutput(_FrozenWorkerContract):
    """Signed receipt plus same-response fields directly consumable by the loop."""

    schema_version: Literal["adaptive-transport-gateway-worker-output-v2"] = (
        "adaptive-transport-gateway-worker-output-v2"
    )
    signed_receipt: SignedAdaptiveTransportGatewayReceipt
    completion: AdaptiveTransportGatewayCompletionPayload | None = None
    worker_output_hash: Sha256

    @model_validator(mode="after")
    def _validate_output(self) -> AdaptiveTransportGatewayWorkerOutput:
        receipt = self.signed_receipt.receipt
        completion_expected = (
            isinstance(receipt, AdaptiveTransportGatewayReceipt)
            and receipt.completion_fields_available
        )
        if completion_expected != (self.completion is not None):
            raise ValueError("worker completion presence disagrees with its signed receipt")
        if self.completion is not None:
            completion = self.completion
            if not isinstance(receipt, AdaptiveTransportGatewayReceipt):
                raise ValueError("transport failure cannot expose a completion")
            if (
                completion.provider_response_model,
                completion.provider_response_model_utf8_sha256,
                completion.visible_output_utf8_sha256,
                completion.reasoning_output_utf8_sha256,
                completion.usage_canonical_json_sha256,
            ) != (
                receipt.provider_response_model,
                receipt.provider_response_model_utf8_sha256,
                receipt.visible_output_utf8_sha256,
                receipt.reasoning_output_utf8_sha256,
                receipt.usage_canonical_json_sha256,
            ):
                raise ValueError("worker completion fields disagree with the signed receipt")
        if self.worker_output_hash != canonical_sha256(
            self.model_dump(mode="json", exclude={"worker_output_hash"})
        ):
            raise ValueError("gateway worker output hash mismatch")
        return self


@dataclass(frozen=True)
class _GatewayHTTPSExchange:
    response_body: bytes
    http_status_code: int
    connected_ip: str
    tls_peer_certificate_sha256: str
    tls_peer_spki_sha256: str
    tls_protocol: Literal["TLSv1.2", "TLSv1.3"]


class _GatewayTransportFailure(RuntimeError):
    def __init__(
        self,
        *,
        stage: Literal[
            "dns_resolution",
            "tcp_connect",
            "tls_handshake",
            "request_write",
            "response_headers",
        ],
        error: BaseException,
        connected_ip: str | None = None,
        tls_peer_certificate_sha256: str | None = None,
        tls_peer_spki_sha256: str | None = None,
    ) -> None:
        super().__init__(type(error).__name__)
        self.stage = stage
        self.error_type = type(error).__name__
        # The message is hashed before publication.  Keep it available only inside
        # this short-lived worker so the signed failure can distinguish incidents.
        self.error_message = str(error) or type(error).__name__
        self.connected_ip = connected_ip
        self.tls_peer_certificate_sha256 = tls_peer_certificate_sha256
        self.tls_peer_spki_sha256 = tls_peer_spki_sha256


def build_adaptive_transport_gateway_worker_request(
    *,
    request_commitment: AdaptiveTransportRequestCommitment,
    request_bytes: bytes,
) -> AdaptiveTransportGatewayWorkerRequest:
    """Build canonical stdin for a separately launched worker process."""

    if not isinstance(request_bytes, bytes):
        raise AdaptiveTransportGatewayWorkerError("worker request must use exact bytes")
    values: dict[str, Any] = {
        "schema_version": "adaptive-transport-gateway-worker-request-v1",
        "request_commitment": request_commitment.model_dump(mode="json"),
        "request_payload_base64": base64.b64encode(request_bytes).decode("ascii"),
    }
    values["worker_request_hash"] = canonical_sha256(values)
    return AdaptiveTransportGatewayWorkerRequest.model_validate(values)


def load_adaptive_transport_gateway_worker_request(
    payload: bytes,
) -> AdaptiveTransportGatewayWorkerRequest:
    """Load exact canonical stdin bytes with no trailing whitespace or downgrade."""

    if not isinstance(payload, bytes) or len(payload) > _MAX_STDIN_BYTES:
        raise AdaptiveTransportGatewayWorkerError("gateway worker stdin size is invalid")
    try:
        text = payload.decode("utf-8")
        request = AdaptiveTransportGatewayWorkerRequest.model_validate_json(text)
    except Exception as exc:
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker stdin is not the canonical v1 request"
        ) from exc
    if payload != canonical_json(request).encode("utf-8"):
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker stdin has non-canonical or trailing bytes"
        )
    return request


def load_adaptive_transport_gateway_worker_output(
    payload: bytes,
) -> AdaptiveTransportGatewayWorkerOutput:
    """Load exact canonical stdout and recheck completion-to-receipt hashes."""

    if not isinstance(payload, bytes) or len(payload) > _MAX_STDIN_BYTES:
        raise AdaptiveTransportGatewayWorkerError("gateway worker stdout size is invalid")
    try:
        text = payload.decode("utf-8")
        output = AdaptiveTransportGatewayWorkerOutput.model_validate_json(text)
    except Exception as exc:
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker stdout is not the canonical v2 output"
        ) from exc
    if payload != canonical_json(output).encode("utf-8"):
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker stdout has non-canonical or trailing bytes"
        )
    return output


def adaptive_transport_gateway_worker_trust_manifest() -> (
    AdaptiveTransportGatewayWorkerTrustManifest
):
    """Return source/build hashes for out-of-band operator pinning."""

    protocol_path = Path(
        sys.modules[build_transport_gateway_request_commitment.__module__].__file__ or ""
    )
    worker_path = Path(__file__)
    source_entries = []
    for label, path in sorted(
        (("protocol", protocol_path), ("worker", worker_path)),
        key=lambda item: item[0],
    ):
        payload = path.read_bytes()
        source_entries.append(
            {"label": label, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
        )
    source_hash = canonical_sha256(source_entries)
    executable = Path(sys.executable)
    executable_hash = (
        hashlib.sha256(executable.read_bytes()).hexdigest()
        if executable.is_file()
        else canonical_sha256(str(executable))
    )
    build_payload = {
        "schema_version": "adaptive-transport-gateway-worker-build-v1",
        "source_sha256": source_hash,
        "python_executable_sha256": executable_hash,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "openssl_version": ssl.OPENSSL_VERSION,
        "cryptography_version": importlib.metadata.version("cryptography"),
    }
    values: dict[str, Any] = {
        "schema_version": "adaptive-transport-gateway-worker-trust-manifest-v1",
        "gateway_source_sha256": source_hash,
        "gateway_build_sha256": canonical_sha256(build_payload),
        "python_implementation": build_payload["python_implementation"],
        "python_version": build_payload["python_version"],
        "openssl_version": build_payload["openssl_version"],
        "cryptography_version": build_payload["cryptography_version"],
    }
    values["manifest_hash"] = canonical_sha256(values)
    return AdaptiveTransportGatewayWorkerTrustManifest.model_validate(values)


def _run_worker_once(
    stdin_payload: bytes,
    *,
    environment: Mapping[str, str],
    now_utc: datetime,
) -> bytes:
    request = load_adaptive_transport_gateway_worker_request(stdin_payload)
    commitment = request.request_commitment
    request_bytes = request.request_bytes()
    origins = _required_csv(environment, _ORIGINS_ENV)
    expected_provider = _required_environment_value(environment, _PROVIDER_ENV)
    expected_model = _required_environment_value(environment, _MODEL_ENV)
    if (commitment.provider_name, commitment.model_name) != (
        expected_provider,
        expected_model,
    ):
        raise AdaptiveTransportGatewayWorkerError(
            "gateway request provider/model is not allowed by worker policy"
        )
    rebuilt = build_transport_gateway_request_commitment(
        request_bytes=request_bytes,
        request_id=commitment.request_id,
        provider_name=commitment.provider_name,
        model_name=commitment.model_name,
        request_url=commitment.request_url,
        allowlisted_origins=origins,
        nonce=commitment.nonce,
        issued_at_utc=commitment.issued_at_utc,
        cell_id=commitment.cell_id,
        trajectory_id=commitment.trajectory_id,
        reservation_id=commitment.reservation_id,
        reservation_hash=commitment.reservation_hash,
        pre_call_id=commitment.pre_call_id,
        pre_call_hash=commitment.pre_call_hash,
        max_redirects=commitment.max_redirects,
    )
    if rebuilt != commitment:
        raise AdaptiveTransportGatewayWorkerError(
            "gateway request commitment does not replay from exact bytes"
        )
    if commitment.max_redirects != 0:
        raise AdaptiveTransportGatewayWorkerError(
            "the v1 worker forbids redirects; commitment max_redirects must be zero"
        )
    nonce_root = Path(_required_environment_value(environment, _NONCE_LEDGER_ENV))
    TransportGatewayRequestNonceLedger(nonce_root).reserve_once(
        commitment,
        reserved_at_utc=now_utc,
    )
    api_key = _required_environment_value(environment, _API_KEY_ENV)
    timeout_seconds = _timeout_seconds(environment)
    private_key = _load_private_key(environment)
    manifest = adaptive_transport_gateway_worker_trust_manifest()
    receipt_id = f"gateway-{commitment.request_id}"
    receipt: AdaptiveTransportGatewayReceiptEvidence
    completion: AdaptiveTransportGatewayCompletionPayload | None
    try:
        exchange = _perform_https_exchange(
            commitment=commitment,
            request_bytes=request_bytes,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        terminal_at = datetime.now(timezone.utc).replace(microsecond=0)
        completion = extract_adaptive_transport_gateway_completion(
            response_body=exchange.response_body,
            http_status_code=exchange.http_status_code,
            expected_model_name=commitment.model_name,
        )
        receipt = build_adaptive_transport_gateway_receipt(
            gateway_receipt_id=receipt_id,
            request_commitment=commitment,
            transmitted_request_bytes=request_bytes,
            completed_at_utc=_utc_text(terminal_at),
            final_url=commitment.request_url,
            http_status_code=exchange.http_status_code,
            connected_ip=exchange.connected_ip,
            tls_protocol=exchange.tls_protocol,
            response_body=exchange.response_body,
            gateway_build_sha256=manifest.gateway_build_sha256,
            gateway_source_sha256=manifest.gateway_source_sha256,
            tls_peer_certificate_sha256=exchange.tls_peer_certificate_sha256,
            tls_peer_spki_sha256=exchange.tls_peer_spki_sha256,
        )
    except _GatewayTransportFailure as failure:
        terminal_at = datetime.now(timezone.utc).replace(microsecond=0)
        completion = None
        receipt = build_adaptive_transport_gateway_failure_receipt(
            gateway_receipt_id=receipt_id,
            request_commitment=commitment,
            observed_request_bytes=request_bytes,
            failed_at_utc=_utc_text(terminal_at),
            failure_stage=failure.stage,
            attempted_url=commitment.request_url,
            error_type=failure.error_type,
            error_message=failure.error_message,
            gateway_build_sha256=manifest.gateway_build_sha256,
            gateway_source_sha256=manifest.gateway_source_sha256,
            connected_ip=failure.connected_ip,
            tls_peer_certificate_sha256=failure.tls_peer_certificate_sha256,
            tls_peer_spki_sha256=failure.tls_peer_spki_sha256,
        )
    signature = private_key.sign(transport_gateway_receipt_signature_message(receipt))
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    signed = build_signed_adaptive_transport_gateway_receipt(
        receipt=receipt,
        gateway_public_key_pem=public_pem,
        signature_base64=base64.b64encode(signature).decode("ascii"),
    )
    output_values: dict[str, Any] = {
        "schema_version": "adaptive-transport-gateway-worker-output-v2",
        "signed_receipt": signed.model_dump(mode="json"),
        "completion": (completion.model_dump(mode="json") if completion is not None else None),
    }
    output_values["worker_output_hash"] = canonical_sha256(output_values)
    output = AdaptiveTransportGatewayWorkerOutput.model_validate(output_values)
    return canonical_json(output).encode("utf-8")


def _perform_https_exchange(
    *,
    commitment: AdaptiveTransportRequestCommitment,
    request_bytes: bytes,
    api_key: str,
    timeout_seconds: int,
) -> _GatewayHTTPSExchange:
    parsed = urllib.parse.urlsplit(commitment.request_url)
    hostname = parsed.hostname
    if hostname is None:
        raise AdaptiveTransportGatewayWorkerError("committed gateway URL has no hostname")
    connection = http.client.HTTPSConnection(
        hostname,
        parsed.port or 443,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    connected_ip: str | None = None
    certificate_hash: str | None = None
    spki_hash: str | None = None
    tls_protocol: Literal["TLSv1.2", "TLSv1.3"] | None = None
    try:
        try:
            connection.connect()
        except socket.gaierror as exc:
            raise _GatewayTransportFailure(stage="dns_resolution", error=exc) from exc
        except ssl.SSLError as exc:
            raise _GatewayTransportFailure(stage="tls_handshake", error=exc) from exc
        except OSError as exc:
            raise _GatewayTransportFailure(stage="tcp_connect", error=exc) from exc
        tls_socket = connection.sock
        if tls_socket is None:
            raise AdaptiveTransportGatewayWorkerError(
                "HTTPS connection did not expose its verified TLS socket"
            )
        peer = tls_socket.getpeername()[0]
        connected_ip = ipaddress.ip_address(peer).compressed
        if not ipaddress.ip_address(connected_ip).is_global:
            raise AdaptiveTransportGatewayWorkerError("gateway connected to a non-global address")
        certificate_der = tls_socket.getpeercert(binary_form=True)
        if not certificate_der:
            raise AdaptiveTransportGatewayWorkerError(
                "gateway TLS socket did not expose a peer certificate"
            )
        certificate_hash = hashlib.sha256(certificate_der).hexdigest()
        certificate = x509.load_der_x509_certificate(certificate_der)
        spki_der = certificate.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        spki_hash = hashlib.sha256(spki_der).hexdigest()
        negotiated = tls_socket.version()
        if negotiated == "TLSv1.2":
            tls_protocol = "TLSv1.2"
        elif negotiated == "TLSv1.3":
            tls_protocol = "TLSv1.3"
        else:
            raise AdaptiveTransportGatewayWorkerError("gateway negotiated a forbidden TLS version")
        try:
            connection.request(
                "POST",
                parsed.path,
                body=request_bytes,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-AutoResearch-Request-ID": commitment.request_id,
                },
            )
        except (OSError, http.client.HTTPException) as exc:
            raise _GatewayTransportFailure(
                stage="request_write",
                error=exc,
                connected_ip=connected_ip,
                tls_peer_certificate_sha256=certificate_hash,
                tls_peer_spki_sha256=spki_hash,
            ) from exc
        try:
            response = connection.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            raise _GatewayTransportFailure(
                stage="response_headers",
                error=exc,
                connected_ip=connected_ip,
                tls_peer_certificate_sha256=certificate_hash,
                tls_peer_spki_sha256=spki_hash,
            ) from exc
        response_body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(response_body) > _MAX_RESPONSE_BYTES:
            raise AdaptiveTransportGatewayWorkerError(
                "gateway provider response exceeds the fixed size limit"
            )
        if response.status in {301, 302, 303, 307, 308}:
            raise AdaptiveTransportGatewayWorkerError("gateway v1 refuses every provider redirect")
        if tls_protocol is None:
            raise AdaptiveTransportGatewayWorkerError("gateway TLS version was not recorded")
        return _GatewayHTTPSExchange(
            response_body=response_body,
            http_status_code=response.status,
            connected_ip=connected_ip,
            tls_peer_certificate_sha256=certificate_hash,
            tls_peer_spki_sha256=spki_hash,
            tls_protocol=tls_protocol,
        )
    finally:
        connection.close()


def _load_private_key(environment: Mapping[str, str]) -> Ed25519PrivateKey:
    fd_text = environment.get(_PRIVATE_KEY_FD_ENV)
    pem_text = environment.get(_PRIVATE_KEY_PEM_ENV)
    if bool(fd_text) == bool(pem_text):
        raise AdaptiveTransportGatewayWorkerError(
            "configure exactly one worker-only private-key FD or environment value"
        )
    if fd_text:
        try:
            descriptor = int(fd_text)
            if descriptor < 3:
                raise ValueError
            with os.fdopen(os.dup(descriptor), "rb", closefd=True) as handle:
                private_pem = handle.read(_MAX_PRIVATE_KEY_BYTES + 1)
        except (OSError, ValueError) as exc:
            raise AdaptiveTransportGatewayWorkerError(
                "worker private-key file descriptor is invalid"
            ) from exc
    else:
        try:
            private_pem = (pem_text or "").encode("ascii")
        except UnicodeEncodeError as exc:
            raise AdaptiveTransportGatewayWorkerError(
                "worker private key environment value is not ASCII PEM"
            ) from exc
    if not private_pem or len(private_pem) > _MAX_PRIVATE_KEY_BYTES:
        raise AdaptiveTransportGatewayWorkerError("worker private key size is invalid")
    try:
        loaded = serialization.load_pem_private_key(private_pem, password=None)
    except (TypeError, ValueError) as exc:
        raise AdaptiveTransportGatewayWorkerError(
            "worker private key is not an unencrypted PEM key"
        ) from exc
    if not isinstance(loaded, Ed25519PrivateKey):
        raise AdaptiveTransportGatewayWorkerError("worker private key must use Ed25519")
    canonical_pem = loaded.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    if private_pem != canonical_pem:
        raise AdaptiveTransportGatewayWorkerError(
            "worker private key must use canonical unencrypted PKCS8 PEM"
        )
    return loaded


def _decode_canonical_base64(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker request payload is not canonical base64"
        ) from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker request payload has non-canonical pad bits"
        )
    return decoded


def _required_environment_value(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value.strip() or value != value.strip():
        raise AdaptiveTransportGatewayWorkerError(
            f"required gateway worker environment setting is missing: {name}"
        )
    return value


def _required_csv(environment: Mapping[str, str], name: str) -> tuple[str, ...]:
    raw = _required_environment_value(environment, name)
    values = tuple(raw.split(","))
    if any(not value or value != value.strip() for value in values):
        raise AdaptiveTransportGatewayWorkerError(
            f"gateway worker list setting is not canonical: {name}"
        )
    return values


def _timeout_seconds(environment: Mapping[str, str]) -> int:
    raw = environment.get(_TIMEOUT_ENV, "120")
    try:
        value = int(raw)
    except ValueError as exc:
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker timeout is not an integer"
        ) from exc
    if not 1 <= value <= 300 or str(value) != raw:
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker timeout must be canonical and within 1-300 seconds"
        )
    return value


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AdaptiveTransportGatewayWorkerError("gateway worker clock is timezone-naive")
    canonical = value.astimezone(timezone.utc)
    if canonical.microsecond:
        raise AdaptiveTransportGatewayWorkerError(
            "gateway worker clock must have whole-second precision"
        )
    return canonical.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--print-trust-manifest":
        sys.stdout.write(canonical_json(adaptive_transport_gateway_worker_trust_manifest()))
        return 0
    if len(sys.argv) != 1:
        sys.stderr.write("adaptive transport gateway worker: invalid arguments\n")
        return 2
    stdin_payload = sys.stdin.buffer.read(_MAX_STDIN_BYTES + 1)
    try:
        output = _run_worker_once(
            stdin_payload,
            environment=os.environ,
            now_utc=datetime.now(timezone.utc).replace(microsecond=0),
        )
    except (AdaptiveTransportGatewayError, AdaptiveTransportGatewayWorkerError):
        # Do not print exception text: provider, filesystem, or TLS libraries may
        # include environment-derived material in their messages.
        sys.stderr.write("adaptive transport gateway worker: request failed closed\n")
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
