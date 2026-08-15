"""Adversarial tests for the independently signed transport-gateway boundary."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_json, canonical_sha256
from autoresearch.research import adaptive_transport_gateway_worker as gateway_worker
from autoresearch.research.adaptive_transport_gateway import (
    AdaptiveTransportGatewayError,
    AdaptiveTransportGatewayFailureReceipt,
    AdaptiveTransportGatewayReceipt,
    AdaptiveTransportRedirectHop,
    AdaptiveTransportRequestCommitment,
    SignedAdaptiveTransportGatewayReceipt,
    TransportGatewayReplayLedger,
    VerifiedAdaptiveTransportGatewayAttestation,
    build_adaptive_transport_gateway_failure_receipt,
    build_adaptive_transport_gateway_receipt,
    build_signed_adaptive_transport_gateway_receipt,
    build_transport_gateway_request_commitment,
    load_signed_adaptive_transport_gateway_receipt,
    replay_verify_adaptive_transport_gateway_attestation,
    transport_gateway_receipt_signature_message,
    verify_adaptive_transport_gateway_receipt,
)

ORIGIN = "https://dashscope.aliyuncs.com"
REQUEST_URL = f"{ORIGIN}/compatible-mode/v1/chat/completions"
MODEL = "qwen3.7-max"
NOW = datetime(2026, 8, 10, 3, 0, 3, tzinfo=timezone.utc)
ISSUED_AT = "2026-08-10T03:00:00Z"
COMPLETED_AT = "2026-08-10T03:00:02Z"
BUILD_HASH = "b" * 64
SOURCE_HASH = "c" * 64
TLS_CERT_HASH = "d" * 64


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _request_bytes(
    *,
    model: str = MODEL,
    messages: list[dict[str, str]] | None = None,
) -> bytes:
    return _canonical_bytes(
        {
            "messages": messages
            or [
                {"role": "system", "content": "你是科研主代理。"},
                {"role": "user", "content": "自主选择下一研究动作。"},
            ],
            "model": model,
            "temperature": 0.2,
        }
    )


def _response_bytes(
    *,
    response_id: str = "provider-secret-response-id",
    response_model: str | None = MODEL,
) -> bytes:
    payload: dict[str, Any] = {
        "choices": [
            {
                "message": {
                    "content": '{"operator":"branch_hypothesis"}',
                    "reasoning_content": "有界推理摘要",
                }
            }
        ],
        "id": response_id,
        "usage": {"completion_tokens": 11, "prompt_tokens": 29},
    }
    if response_model is not None:
        payload["model"] = response_model
    return _canonical_bytes(payload)


def _commitment(
    *,
    request_bytes: bytes | None = None,
    model: str = MODEL,
    request_url: str = REQUEST_URL,
    allowlisted_origins: tuple[str, ...] = (ORIGIN,),
    nonce: str = "01" * 16,
    issued_at: str = ISSUED_AT,
    cell_id: str = "cell.blind-001",
    trajectory_id: str = "trajectory.blind-001",
) -> AdaptiveTransportRequestCommitment:
    return build_transport_gateway_request_commitment(
        request_bytes=request_bytes or _request_bytes(model=model),
        request_id="request-0001",
        provider_name="qwen",
        model_name=model,
        request_url=request_url,
        allowlisted_origins=allowlisted_origins,
        nonce=nonce,
        issued_at_utc=issued_at,
        cell_id=cell_id,
        trajectory_id=trajectory_id,
        reservation_id="reservation-0001",
        reservation_hash="1" * 64,
        pre_call_id="precall-0001",
        pre_call_hash="2" * 64,
        max_redirects=0,
    )


def _receipt(
    commitment: AdaptiveTransportRequestCommitment | None = None,
    *,
    status: int = 200,
    response_body: bytes | None = None,
    connected_ip: str = "8.8.8.8",
) -> AdaptiveTransportGatewayReceipt:
    commitment = commitment or _commitment()
    body = response_body or (
        _response_bytes() if 200 <= status < 300 else _canonical_bytes({"error": "quota"})
    )
    return build_adaptive_transport_gateway_receipt(
        gateway_receipt_id="gateway-receipt-0001",
        request_commitment=commitment,
        transmitted_request_bytes=_request_bytes(model=commitment.model_name),
        completed_at_utc=COMPLETED_AT,
        final_url=commitment.request_url,
        http_status_code=status,
        connected_ip=connected_ip,
        tls_protocol="TLSv1.3",
        response_body=body,
        gateway_build_sha256=BUILD_HASH,
        gateway_source_sha256=SOURCE_HASH,
        tls_peer_certificate_sha256=TLS_CERT_HASH,
    )


def _key_material() -> tuple[Ed25519PrivateKey, str, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem, hashlib.sha256(public_der).hexdigest()


def _signed(
    receipt: AdaptiveTransportGatewayReceipt | AdaptiveTransportGatewayFailureReceipt,
    *,
    key_material: tuple[Ed25519PrivateKey, str, str] | None = None,
) -> tuple[SignedAdaptiveTransportGatewayReceipt, str]:
    private_key, public_pem, fingerprint = key_material or _key_material()
    signature = base64.b64encode(
        private_key.sign(transport_gateway_receipt_signature_message(receipt))
    ).decode("ascii")
    return (
        build_signed_adaptive_transport_gateway_receipt(
            receipt=receipt,
            gateway_public_key_pem=public_pem,
            signature_base64=signature,
        ),
        fingerprint,
    )


def _verify(
    signed: SignedAdaptiveTransportGatewayReceipt,
    fingerprint: str,
    commitment: AdaptiveTransportRequestCommitment,
    tmp_path: Path,
    *,
    now: datetime = NOW,
    origins: tuple[str, ...] = (ORIGIN,),
) -> Any:
    return verify_adaptive_transport_gateway_receipt(
        signed,
        expected_request_commitment=commitment,
        trusted_public_key_sha256=fingerprint,
        trusted_gateway_build_sha256=BUILD_HASH,
        trusted_gateway_source_sha256=SOURCE_HASH,
        allowlisted_origins=origins,
        now_utc=now,
        replay_ledger=TransportGatewayReplayLedger(tmp_path / "verifier-nonces"),
    )


def _replay(
    signed: SignedAdaptiveTransportGatewayReceipt,
    fingerprint: str,
    commitment: AdaptiveTransportRequestCommitment,
    accepted: VerifiedAdaptiveTransportGatewayAttestation,
    tmp_path: Path,
) -> Any:
    return replay_verify_adaptive_transport_gateway_attestation(
        signed,
        expected_request_commitment=commitment,
        accepted_attestation=accepted,
        trusted_public_key_sha256=fingerprint,
        trusted_gateway_build_sha256=BUILD_HASH,
        trusted_gateway_source_sha256=SOURCE_HASH,
        allowlisted_origins=(ORIGIN,),
        replay_ledger=TransportGatewayReplayLedger(tmp_path / "verifier-nonces"),
    )


def _readdress(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    rewritten = dict(payload)
    rewritten.pop(hash_field, None)
    rewritten[hash_field] = canonical_sha256(rewritten)
    return rewritten


def test_valid_signed_gateway_exchange_binds_exact_request_and_response(
    tmp_path: Path,
) -> None:
    commitment = _commitment()
    receipt = _receipt(commitment)
    signed, fingerprint = _signed(receipt)

    verified = _verify(signed, fingerprint, commitment, tmp_path)

    request_messages = json.loads(_request_bytes().decode("utf-8"))["messages"]
    assert commitment.request_messages_sha256 == canonical_sha256(request_messages)
    assert (
        receipt.visible_output_utf8_sha256
        == hashlib.sha256(b'{"operator":"branch_hypothesis"}').hexdigest()
    )
    assert (
        receipt.reasoning_output_utf8_sha256 == hashlib.sha256("有界推理摘要".encode()).hexdigest()
    )
    assert verified.outcome == "http_response"
    assert verified.http_response_received is True
    assert verified.provider_completion_eligible is True
    assert verified.formal_transport_eligible is True
    assert verified.process_local_client_trace_promoted is False
    assert receipt.provider_response_model == MODEL
    assert (
        receipt.provider_response_model_utf8_sha256
        == hashlib.sha256(MODEL.encode("utf-8")).hexdigest()
    )
    assert receipt.provider_response_model_matches_committed_model is True
    assert len(list((tmp_path / "verifier-nonces").glob("*.json"))) == 1
    serialized = canonical_json(receipt)
    assert "provider-secret-response-id" not in serialized
    assert hashlib.sha256(b"provider-secret-response-id").hexdigest() in serialized


def test_signed_http_failure_is_formal_transport_but_not_a_completion(tmp_path: Path) -> None:
    commitment = _commitment()
    receipt = _receipt(commitment, status=429)
    signed, fingerprint = _signed(receipt)

    verified = _verify(signed, fingerprint, commitment, tmp_path)

    assert verified.outcome == "http_response"
    assert verified.http_response_received is True
    assert verified.provider_completion_eligible is False
    assert verified.formal_transport_eligible is True
    assert receipt.completion_fields_available is False


def test_signed_pre_response_failure_is_charged_evidence_not_completion(
    tmp_path: Path,
) -> None:
    commitment = _commitment()
    failure = build_adaptive_transport_gateway_failure_receipt(
        gateway_receipt_id="gateway-failure-0001",
        request_commitment=commitment,
        observed_request_bytes=_request_bytes(),
        failed_at_utc=COMPLETED_AT,
        failure_stage="tls_handshake",
        attempted_url=REQUEST_URL,
        error_type="SSLError",
        error_message="certificate verification failed",
        gateway_build_sha256=BUILD_HASH,
        gateway_source_sha256=SOURCE_HASH,
        connected_ip="8.8.8.8",
    )
    signed, fingerprint = _signed(failure)

    verified = _verify(signed, fingerprint, commitment, tmp_path)

    assert verified.outcome == "transport_failure"
    assert verified.http_response_received is False
    assert verified.provider_completion_eligible is False
    assert verified.formal_transport_eligible is True
    assert "certificate verification failed" not in canonical_json(failure)


def test_self_minted_key_cannot_replace_external_trust_anchor(tmp_path: Path) -> None:
    commitment = _commitment()
    signed, _ = _signed(_receipt(commitment))
    _, _, actual_external_fingerprint = _key_material()

    with pytest.raises(AdaptiveTransportGatewayError, match="external trust anchor"):
        _verify(signed, actual_external_fingerprint, commitment, tmp_path)


def test_verifier_has_no_default_or_artifact_derived_trust_policy() -> None:
    parameters = inspect.signature(verify_adaptive_transport_gateway_receipt).parameters
    for name in (
        "trusted_public_key_sha256",
        "trusted_gateway_build_sha256",
        "trusted_gateway_source_sha256",
        "allowlisted_origins",
        "now_utc",
        "replay_ledger",
    ):
        assert parameters[name].default is inspect.Parameter.empty


@pytest.mark.parametrize(
    "request_url,origins",
    (
        ("http://dashscope.aliyuncs.com/v1/chat/completions", (ORIGIN,)),
        ("https://localhost/v1/chat/completions", ("https://localhost",)),
        ("https://127.0.0.1/v1/chat/completions", ("https://127.0.0.1",)),
        ("https://10.0.0.8/v1/chat/completions", ("https://10.0.0.8",)),
        ("https://[::1]/v1/chat/completions", ("https://[::1]",)),
    ),
)
def test_http_localhost_and_private_origins_fail_before_commitment(
    request_url: str,
    origins: tuple[str, ...],
) -> None:
    with pytest.raises(AdaptiveTransportGatewayError):
        _commitment(request_url=request_url, allowlisted_origins=origins)


def test_unallowlisted_public_origin_fails_before_commitment() -> None:
    with pytest.raises(AdaptiveTransportGatewayError, match="allowlisted"):
        _commitment(allowlisted_origins=("https://example.com",))


def test_request_body_model_mismatch_fails_before_transport() -> None:
    with pytest.raises(AdaptiveTransportGatewayError, match="body model"):
        _commitment(request_bytes=_request_bytes(model="qwen-other"), model=MODEL)


@pytest.mark.parametrize("response_model", (None, "", "qwen3.7-plus", f" {MODEL}"))
def test_success_response_model_must_exactly_match_pre_call_commitment(
    response_model: str | None,
) -> None:
    with pytest.raises(AdaptiveTransportGatewayError, match="provider model|exactly match"):
        _receipt(response_body=_response_bytes(response_model=response_model))


@pytest.mark.parametrize(
    "field",
    ("cell", "trajectory", "model", "origin", "request"),
)
def test_valid_signature_cannot_cross_request_or_lineage_boundaries(
    tmp_path: Path,
    field: str,
) -> None:
    expected = _commitment()
    if field == "cell":
        actual = _commitment(cell_id="cell.blind-002")
    elif field == "trajectory":
        actual = _commitment(trajectory_id="trajectory.blind-002")
    elif field == "model":
        actual = _commitment(model="qwen3.7-plus")
    elif field == "origin":
        actual = _commitment(
            request_url="https://example.com/v1/chat/completions",
            allowlisted_origins=("https://example.com",),
        )
    else:
        actual = _commitment(
            request_bytes=_request_bytes(messages=[{"role": "user", "content": "不同的请求"}])
        )
    if field == "request":
        different_bytes = _request_bytes(messages=[{"role": "user", "content": "不同的请求"}])
        receipt = build_adaptive_transport_gateway_receipt(
            gateway_receipt_id="gateway-receipt-0002",
            request_commitment=actual,
            transmitted_request_bytes=different_bytes,
            completed_at_utc=COMPLETED_AT,
            final_url=actual.request_url,
            http_status_code=200,
            connected_ip="8.8.8.8",
            tls_protocol="TLSv1.3",
            response_body=_response_bytes(),
            gateway_build_sha256=BUILD_HASH,
            gateway_source_sha256=SOURCE_HASH,
            tls_peer_certificate_sha256=TLS_CERT_HASH,
        )
    else:
        receipt = _receipt(
            actual,
            response_body=_response_bytes(response_model=actual.model_name),
        )
    signed, fingerprint = _signed(receipt)

    with pytest.raises(AdaptiveTransportGatewayError, match="expected request or lineage"):
        _verify(
            signed,
            fingerprint,
            expected,
            tmp_path,
            origins=(ORIGIN, "https://example.com"),
        )


def test_readdressed_receipt_tamper_without_gateway_resign_fails(tmp_path: Path) -> None:
    commitment = _commitment()
    receipt = _receipt(commitment)
    signed, fingerprint = _signed(receipt)
    receipt_payload = receipt.model_dump(mode="json")
    receipt_payload["http_status_code"] = 201
    forged_receipt = AdaptiveTransportGatewayReceipt.model_validate(
        _readdress(receipt_payload, "receipt_hash")
    )
    signed_payload = signed.model_dump(mode="json")
    signed_payload["receipt"] = forged_receipt.model_dump(mode="json")
    forged_envelope = SignedAdaptiveTransportGatewayReceipt.model_validate(
        _readdress(signed_payload, "envelope_hash")
    )

    with pytest.raises(AdaptiveTransportGatewayError, match="signature verification failed"):
        _verify(forged_envelope, fingerprint, commitment, tmp_path)


def test_nonce_is_accepted_once_even_for_identical_signed_receipt(tmp_path: Path) -> None:
    commitment = _commitment()
    signed, fingerprint = _signed(_receipt(commitment))
    _verify(signed, fingerprint, commitment, tmp_path)

    with pytest.raises(AdaptiveTransportGatewayError, match="already been observed"):
        _verify(signed, fingerprint, commitment, tmp_path)


def test_post_run_replay_reverifies_old_receipt_without_reconsuming_nonce(
    tmp_path: Path,
) -> None:
    commitment = _commitment()
    signed, fingerprint = _signed(_receipt(commitment))
    accepted = _verify(signed, fingerprint, commitment, tmp_path)
    ledger = TransportGatewayReplayLedger(tmp_path / "verifier-nonces")

    first = _replay(signed, fingerprint, commitment, accepted, tmp_path)
    second = _replay(signed, fingerprint, commitment, accepted, tmp_path)

    assert first == second
    assert first.original_accepted_at_utc == NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert first.original_freshness_replayed is True
    assert first.local_antireplay_integrity_replayed is True
    assert first.local_ledger_is_independent_acceptance_evidence is False
    assert first.nonce_was_not_reconsumed is True
    assert first.provider_completion_eligible is True
    assert len(list(ledger.root.glob("*.json"))) == 1


def test_post_run_replay_rejects_self_readdressed_attestation(tmp_path: Path) -> None:
    commitment = _commitment()
    signed, fingerprint = _signed(_receipt(commitment))
    accepted = _verify(signed, fingerprint, commitment, tmp_path)
    payload = accepted.model_dump(mode="json")
    payload["provider_completion_eligible"] = False
    forged = VerifiedAdaptiveTransportGatewayAttestation.model_validate(
        _readdress(payload, "attestation_hash")
    )

    with pytest.raises(AdaptiveTransportGatewayError, match="does not replay"):
        replay_verify_adaptive_transport_gateway_attestation(
            signed,
            expected_request_commitment=commitment,
            accepted_attestation=forged,
            trusted_public_key_sha256=fingerprint,
            trusted_gateway_build_sha256=BUILD_HASH,
            trusted_gateway_source_sha256=SOURCE_HASH,
            allowlisted_origins=(ORIGIN,),
            replay_ledger=TransportGatewayReplayLedger(tmp_path / "verifier-nonces"),
        )


def test_post_run_replay_rejects_readdressed_local_antireplay_entry(tmp_path: Path) -> None:
    commitment = _commitment()
    signed, fingerprint = _signed(_receipt(commitment))
    accepted = _verify(signed, fingerprint, commitment, tmp_path)
    ledger = TransportGatewayReplayLedger(tmp_path / "verifier-nonces")
    entry_path = next(ledger.root.glob("*.json"))
    payload = json.loads(entry_path.read_text(encoding="utf-8"))
    payload["attestation_hash"] = "f" * 64
    payload = _readdress(payload, "entry_hash")
    entry_path.write_bytes((canonical_json(payload) + "\n").encode())

    with pytest.raises(AdaptiveTransportGatewayError, match="anti-replay entry disagrees"):
        replay_verify_adaptive_transport_gateway_attestation(
            signed,
            expected_request_commitment=commitment,
            accepted_attestation=accepted,
            trusted_public_key_sha256=fingerprint,
            trusted_gateway_build_sha256=BUILD_HASH,
            trusted_gateway_source_sha256=SOURCE_HASH,
            allowlisted_origins=(ORIGIN,),
            replay_ledger=ledger,
        )


@pytest.mark.parametrize(
    "issued_at,now,error",
    (
        ("2026-08-10T02:54:59Z", NOW, "stale"),
        (
            "2026-08-10T03:00:40Z",
            datetime(2026, 8, 10, 3, 0, 0, tzinfo=timezone.utc),
            "future",
        ),
    ),
)
def test_stale_and_future_commitments_fail(
    tmp_path: Path,
    issued_at: str,
    now: datetime,
    error: str,
) -> None:
    commitment = _commitment(issued_at=issued_at)
    completion = "2026-08-10T03:00:41Z" if error == "future" else "2026-08-10T02:55:01Z"
    receipt = build_adaptive_transport_gateway_receipt(
        gateway_receipt_id="gateway-receipt-time",
        request_commitment=commitment,
        transmitted_request_bytes=_request_bytes(),
        completed_at_utc=completion,
        final_url=REQUEST_URL,
        http_status_code=200,
        connected_ip="8.8.8.8",
        tls_protocol="TLSv1.3",
        response_body=_response_bytes(),
        gateway_build_sha256=BUILD_HASH,
        gateway_source_sha256=SOURCE_HASH,
        tls_peer_certificate_sha256=TLS_CERT_HASH,
    )
    signed, fingerprint = _signed(receipt)

    with pytest.raises(AdaptiveTransportGatewayError, match=error):
        _verify(signed, fingerprint, commitment, tmp_path, now=now)


def test_wrong_gateway_build_or_source_is_not_trusted(tmp_path: Path) -> None:
    commitment = _commitment()
    signed, fingerprint = _signed(_receipt(commitment))

    with pytest.raises(AdaptiveTransportGatewayError, match="gateway build"):
        verify_adaptive_transport_gateway_receipt(
            signed,
            expected_request_commitment=commitment,
            trusted_public_key_sha256=fingerprint,
            trusted_gateway_build_sha256="e" * 64,
            trusted_gateway_source_sha256=SOURCE_HASH,
            allowlisted_origins=(ORIGIN,),
            now_utc=NOW,
            replay_ledger=TransportGatewayReplayLedger(tmp_path / "nonces"),
        )


def test_noncanonical_base64_pad_bits_are_rejected() -> None:
    signed, _ = _signed(_receipt())
    canonical = signed.signature_base64
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    final_value = alphabet.index(canonical[-3])
    noncanonical = canonical[:-3] + alphabet[final_value + 1] + "=="
    assert base64.b64decode(noncanonical, validate=True) == base64.b64decode(
        canonical, validate=True
    )
    payload = signed.model_dump(mode="json")
    payload["signature_base64"] = noncanonical

    with pytest.raises(AdaptiveTransportGatewayError, match="pad bits"):
        SignedAdaptiveTransportGatewayReceipt.model_validate(_readdress(payload, "envelope_hash"))


@pytest.mark.parametrize("suffix", ("\n", "JUNK", "\n-----BEGIN PUBLIC KEY-----"))
def test_public_key_requires_one_canonical_pem_block(suffix: str) -> None:
    signed, _ = _signed(_receipt())
    payload = signed.model_dump(mode="json")
    payload["gateway_public_key_pem"] += suffix

    with pytest.raises(AdaptiveTransportGatewayError, match="canonical"):
        SignedAdaptiveTransportGatewayReceipt.model_validate(_readdress(payload, "envelope_hash"))


def test_redirect_requires_precommitment_and_same_origin() -> None:
    commitment_payload = _commitment().model_dump(mode="json")
    commitment_payload["max_redirects"] = 1
    commitment = AdaptiveTransportRequestCommitment.model_validate(
        _readdress(commitment_payload, "commitment_hash")
    )
    with pytest.raises(ValidationError, match="cross-origin"):
        AdaptiveTransportRedirectHop(
            sequence=1,
            source_url=REQUEST_URL,
            status_code=307,
            target_url="https://example.com/v1/chat/completions",
        )

    same_origin_hop = AdaptiveTransportRedirectHop(
        sequence=1,
        source_url=REQUEST_URL,
        status_code=307,
        target_url=f"{ORIGIN}/compatible-mode/v1/chat/completions-v2",
    )
    with pytest.raises(ValidationError, match="redirect chain"):
        build_adaptive_transport_gateway_receipt(
            gateway_receipt_id="gateway-redirect-disconnected",
            request_commitment=commitment,
            transmitted_request_bytes=_request_bytes(),
            completed_at_utc=COMPLETED_AT,
            final_url=REQUEST_URL,
            http_status_code=200,
            connected_ip="8.8.8.8",
            tls_protocol="TLSv1.3",
            response_body=_response_bytes(),
            gateway_build_sha256=BUILD_HASH,
            gateway_source_sha256=SOURCE_HASH,
            tls_peer_certificate_sha256=TLS_CERT_HASH,
            redirect_chain=(same_origin_hop,),
        )


def test_private_connected_ip_and_missing_tls_peer_fail() -> None:
    with pytest.raises(ValidationError, match="globally routable"):
        _receipt(connected_ip="10.0.0.7")
    with pytest.raises(ValidationError, match="TLS certificate or SPKI"):
        build_adaptive_transport_gateway_receipt(
            gateway_receipt_id="gateway-no-tls-peer",
            request_commitment=_commitment(),
            transmitted_request_bytes=_request_bytes(),
            completed_at_utc=COMPLETED_AT,
            final_url=REQUEST_URL,
            http_status_code=200,
            connected_ip="8.8.8.8",
            tls_protocol="TLSv1.3",
            response_body=_response_bytes(),
            gateway_build_sha256=BUILD_HASH,
            gateway_source_sha256=SOURCE_HASH,
        )


def test_old_process_local_v2_trace_cannot_be_loaded_or_verified(tmp_path: Path) -> None:
    old_trace = {
        "schema_version": "llm-http-transport-trace-v2",
        "request_id": "request-0001",
        "formal_external_anchor_eligible": False,
        "process_local_integrity_only": True,
    }
    with pytest.raises(AdaptiveTransportGatewayError, match="v1 signed schema"):
        load_signed_adaptive_transport_gateway_receipt(_canonical_bytes(old_trace))
    commitment = _commitment()
    untrusted_trace: Any = old_trace
    with pytest.raises(AdaptiveTransportGatewayError, match="process-local traces"):
        verify_adaptive_transport_gateway_receipt(
            untrusted_trace,
            expected_request_commitment=commitment,
            trusted_public_key_sha256="a" * 64,
            trusted_gateway_build_sha256=BUILD_HASH,
            trusted_gateway_source_sha256=SOURCE_HASH,
            allowlisted_origins=(ORIGIN,),
            now_utc=NOW,
            replay_ledger=TransportGatewayReplayLedger(tmp_path / "nonces"),
        )


def test_signed_artifact_loader_requires_exact_canonical_bytes() -> None:
    signed, _ = _signed(_receipt())
    canonical = canonical_json(signed).encode("utf-8")
    assert load_signed_adaptive_transport_gateway_receipt(canonical) == signed
    with pytest.raises(AdaptiveTransportGatewayError, match="non-canonical"):
        load_signed_adaptive_transport_gateway_receipt(canonical + b"\n")


def test_production_protocol_has_no_private_key_or_signing_entrypoint() -> None:
    source = Path(inspect.getfile(verify_adaptive_transport_gateway_receipt)).read_text(
        encoding="utf-8"
    )
    assert "Ed25519PrivateKey" not in source
    assert "generate_private_key" not in source
    assert "PRIVATE_KEY_PEM" not in source


def _worker_environment(
    tmp_path: Path,
    private_key: Ed25519PrivateKey,
) -> dict[str, str]:
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return {
        "AUTORESEARCH_GATEWAY_PRIVATE_KEY_PEM": private_pem,
        "AUTORESEARCH_GATEWAY_PROVIDER_API_KEY": "worker-only-api-secret",
        "AUTORESEARCH_GATEWAY_ALLOWED_ORIGINS": ORIGIN,
        "AUTORESEARCH_GATEWAY_PROVIDER": "qwen",
        "AUTORESEARCH_GATEWAY_MODEL": MODEL,
        "AUTORESEARCH_GATEWAY_REQUEST_NONCE_LEDGER": str(tmp_path / "worker-nonces"),
        "AUTORESEARCH_GATEWAY_TIMEOUT_SECONDS": "30",
    }


def test_one_shot_worker_signs_zero_network_exchange_without_leaking_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    issued_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    commitment = _commitment(issued_at=issued_at, nonce="12" * 16)
    worker_request = gateway_worker.build_adaptive_transport_gateway_worker_request(
        request_commitment=commitment,
        request_bytes=_request_bytes(),
    )
    private_key, _, fingerprint = _key_material()
    environment = _worker_environment(tmp_path, private_key)
    observation = gateway_worker._GatewayHTTPSExchange(
        response_body=_response_bytes(),
        http_status_code=200,
        connected_ip="8.8.8.8",
        tls_peer_certificate_sha256=TLS_CERT_HASH,
        tls_peer_spki_sha256="e" * 64,
        tls_protocol="TLSv1.3",
    )
    monkeypatch.setattr(
        gateway_worker,
        "_perform_https_exchange",
        lambda **_kwargs: observation,
    )

    output = gateway_worker._run_worker_once(
        canonical_json(worker_request).encode("utf-8"),
        environment=environment,
        now_utc=now,
    )
    worker_output = gateway_worker.load_adaptive_transport_gateway_worker_output(output)
    signed = worker_output.signed_receipt
    manifest = gateway_worker.adaptive_transport_gateway_worker_trust_manifest()
    verified = verify_adaptive_transport_gateway_receipt(
        signed,
        expected_request_commitment=commitment,
        trusted_public_key_sha256=fingerprint,
        trusted_gateway_build_sha256=manifest.gateway_build_sha256,
        trusted_gateway_source_sha256=manifest.gateway_source_sha256,
        allowlisted_origins=(ORIGIN,),
        now_utc=datetime.now(timezone.utc).replace(microsecond=0),
        replay_ledger=TransportGatewayReplayLedger(tmp_path / "verifier-worker-nonces"),
    )

    assert verified.provider_completion_eligible is True
    assert worker_output.completion is not None
    assert worker_output.completion.provider_response_model == MODEL
    assert (
        worker_output.completion.provider_response_model_utf8_sha256
        == hashlib.sha256(MODEL.encode("utf-8")).hexdigest()
    )
    assert worker_output.completion.visible_output == '{"operator":"branch_hypothesis"}'
    assert worker_output.completion.reasoning_output == "有界推理摘要"
    assert worker_output.completion.usage == {
        "completion_tokens": 11,
        "prompt_tokens": 29,
    }
    assert isinstance(signed.receipt, AdaptiveTransportGatewayReceipt)
    assert signed.receipt.provider_response_model == MODEL
    assert signed.receipt.provider_response_model_matches_committed_model is True
    assert (
        worker_output.completion.visible_output_utf8_sha256
        == signed.receipt.visible_output_utf8_sha256
    )
    assert (
        worker_output.completion.reasoning_output_utf8_sha256
        == signed.receipt.reasoning_output_utf8_sha256
    )
    assert (
        worker_output.completion.usage_canonical_json_sha256
        == signed.receipt.usage_canonical_json_sha256
    )
    assert b"worker-only-api-secret" not in output
    assert environment["AUTORESEARCH_GATEWAY_PRIVATE_KEY_PEM"].encode() not in output
    assert _request_bytes() not in output
    assert _response_bytes() not in output


def test_one_shot_worker_refuses_mismatched_provider_response_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    commitment = _commitment(
        issued_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        nonce="23" * 16,
    )
    worker_request = gateway_worker.build_adaptive_transport_gateway_worker_request(
        request_commitment=commitment,
        request_bytes=_request_bytes(),
    )
    private_key, _, _ = _key_material()
    monkeypatch.setattr(
        gateway_worker,
        "_perform_https_exchange",
        lambda **_kwargs: gateway_worker._GatewayHTTPSExchange(
            response_body=_response_bytes(response_model="qwen3.7-plus"),
            http_status_code=200,
            connected_ip="8.8.8.8",
            tls_peer_certificate_sha256=TLS_CERT_HASH,
            tls_peer_spki_sha256="e" * 64,
            tls_protocol="TLSv1.3",
        ),
    )

    with pytest.raises(AdaptiveTransportGatewayError, match="exactly match"):
        gateway_worker._run_worker_once(
            canonical_json(worker_request).encode("utf-8"),
            environment=_worker_environment(tmp_path, private_key),
            now_utc=now,
        )


def test_one_shot_worker_signs_transport_failure_and_reserves_nonce_before_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    commitment = _commitment(
        issued_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        nonce="34" * 16,
    )
    worker_request = gateway_worker.build_adaptive_transport_gateway_worker_request(
        request_commitment=commitment,
        request_bytes=_request_bytes(),
    )
    private_key, _, fingerprint = _key_material()
    environment = _worker_environment(tmp_path, private_key)

    def fail_transport(**_kwargs: Any) -> Any:
        raise gateway_worker._GatewayTransportFailure(
            stage="tcp_connect",
            error=TimeoutError("connection timed out with no secret"),
            connected_ip="8.8.8.8",
        )

    monkeypatch.setattr(gateway_worker, "_perform_https_exchange", fail_transport)
    input_bytes = canonical_json(worker_request).encode("utf-8")
    output = gateway_worker._run_worker_once(
        input_bytes,
        environment=environment,
        now_utc=now,
    )
    worker_output = gateway_worker.load_adaptive_transport_gateway_worker_output(output)
    signed = worker_output.signed_receipt
    manifest = gateway_worker.adaptive_transport_gateway_worker_trust_manifest()
    verified = verify_adaptive_transport_gateway_receipt(
        signed,
        expected_request_commitment=commitment,
        trusted_public_key_sha256=fingerprint,
        trusted_gateway_build_sha256=manifest.gateway_build_sha256,
        trusted_gateway_source_sha256=manifest.gateway_source_sha256,
        allowlisted_origins=(ORIGIN,),
        now_utc=datetime.now(timezone.utc).replace(microsecond=0),
        replay_ledger=TransportGatewayReplayLedger(tmp_path / "verifier-failure-nonces"),
    )
    assert verified.outcome == "transport_failure"
    assert verified.provider_completion_eligible is False
    assert worker_output.completion is None
    assert "connection timed out" not in output.decode("utf-8")

    with pytest.raises(AdaptiveTransportGatewayError, match="already reserved"):
        gateway_worker._run_worker_once(
            input_bytes,
            environment=environment,
            now_utc=now,
        )


def test_worker_output_rejects_completion_text_not_bound_by_signed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    commitment = _commitment(
        issued_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        nonce="56" * 16,
    )
    worker_request = gateway_worker.build_adaptive_transport_gateway_worker_request(
        request_commitment=commitment,
        request_bytes=_request_bytes(),
    )
    private_key, _, _ = _key_material()
    monkeypatch.setattr(
        gateway_worker,
        "_perform_https_exchange",
        lambda **_kwargs: gateway_worker._GatewayHTTPSExchange(
            response_body=_response_bytes(),
            http_status_code=200,
            connected_ip="8.8.8.8",
            tls_peer_certificate_sha256=TLS_CERT_HASH,
            tls_peer_spki_sha256="e" * 64,
            tls_protocol="TLSv1.3",
        ),
    )
    output = gateway_worker._run_worker_once(
        canonical_json(worker_request).encode("utf-8"),
        environment=_worker_environment(tmp_path, private_key),
        now_utc=now,
    )
    loaded = gateway_worker.load_adaptive_transport_gateway_worker_output(output)
    payload = loaded.model_dump(mode="json")
    assert isinstance(payload["completion"], dict)
    payload["completion"]["visible_output"] = "伪造的第二份输出"
    payload["completion"]["visible_output_utf8_sha256"] = hashlib.sha256(
        "伪造的第二份输出".encode()
    ).hexdigest()
    payload["completion"] = _readdress(
        payload["completion"],
        "completion_payload_hash",
    )
    payload = _readdress(payload, "worker_output_hash")

    with pytest.raises(
        gateway_worker.AdaptiveTransportGatewayWorkerError,
        match="canonical v2 output",
    ):
        gateway_worker.load_adaptive_transport_gateway_worker_output(_canonical_bytes(payload))


def test_worker_output_rejects_readdressed_response_model_not_bound_by_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    commitment = _commitment(
        issued_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        nonce="67" * 16,
    )
    worker_request = gateway_worker.build_adaptive_transport_gateway_worker_request(
        request_commitment=commitment,
        request_bytes=_request_bytes(),
    )
    private_key, _, _ = _key_material()
    monkeypatch.setattr(
        gateway_worker,
        "_perform_https_exchange",
        lambda **_kwargs: gateway_worker._GatewayHTTPSExchange(
            response_body=_response_bytes(),
            http_status_code=200,
            connected_ip="8.8.8.8",
            tls_peer_certificate_sha256=TLS_CERT_HASH,
            tls_peer_spki_sha256="e" * 64,
            tls_protocol="TLSv1.3",
        ),
    )
    output = gateway_worker._run_worker_once(
        canonical_json(worker_request).encode("utf-8"),
        environment=_worker_environment(tmp_path, private_key),
        now_utc=now,
    )
    loaded = gateway_worker.load_adaptive_transport_gateway_worker_output(output)
    payload = loaded.model_dump(mode="json")
    assert isinstance(payload["completion"], dict)
    payload["completion"]["provider_response_model"] = "qwen3.7-plus"
    payload["completion"]["provider_response_model_utf8_sha256"] = hashlib.sha256(
        b"qwen3.7-plus"
    ).hexdigest()
    payload["completion"] = _readdress(
        payload["completion"],
        "completion_payload_hash",
    )
    payload = _readdress(payload, "worker_output_hash")

    with pytest.raises(
        gateway_worker.AdaptiveTransportGatewayWorkerError,
        match="canonical v2 output",
    ):
        gateway_worker.load_adaptive_transport_gateway_worker_output(_canonical_bytes(payload))
