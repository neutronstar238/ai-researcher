from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.kernel.contracts import canonical_json, canonical_sha256
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkExecutionBundle,
    build_adaptive_loop_benchmark_execution_bundle,
    write_adaptive_loop_benchmark_execution_protocol,
)
from autoresearch.research.adaptive_loop_benchmark_receipts import (
    AdaptiveLoopBenchmarkCellExecutionBinding,
    AdaptiveLoopBenchmarkReceiptBridge,
    AdaptiveLoopBenchmarkReceiptError,
    ArmRuntimeAttestation,
    BudgetLedger,
    BudgetLedgerEntry,
    BudgetOperationKind,
    BudgetOutcome,
    BudgetVector,
    CellJournalEntry,
    CellJournalEventKind,
    CellRuntimeEvidenceBundle,
    ExternalTransportAnchor,
    MechanicalChallengeTransitionReceipt,
    ProviderAttemptReceipt,
    ProviderAttemptStatus,
    ProviderExecutionMode,
    ProviderFailurePhase,
    ProviderPreCallAnchor,
    TerminalEnvelope,
    build_adaptive_loop_benchmark_receipt_bridge,
    build_arm_runtime_attestation,
    build_blind_reveal_package,
    build_budget_ledger,
    build_budget_ledger_entry,
    build_budget_reservation,
    build_cell_journal_entry,
    build_cell_runtime_evidence_bundle,
    build_external_transport_anchor,
    build_mechanical_transition_receipt,
    build_provider_attempt_receipt,
    build_provider_pre_call_anchor,
    build_terminal_envelope,
    load_adaptive_loop_benchmark_receipt_bridge,
    load_cell_journal_entries,
    replay_cell_journal,
    write_adaptive_loop_benchmark_receipt_bridge_once,
    write_benchmark_terminal_set_seal_once,
    write_blind_reveal_package_once,
    write_cell_journal_entry_once,
    write_cell_runtime_evidence_once,
    write_terminal_envelope_once,
)


def _bundle() -> AdaptiveLoopBenchmarkExecutionBundle:
    return build_adaptive_loop_benchmark_execution_bundle(randomization_seed=27_132_026)


def _bridge() -> AdaptiveLoopBenchmarkReceiptBridge:
    return build_adaptive_loop_benchmark_receipt_bridge(_bundle())


def _limit() -> BudgetVector:
    return BudgetVector(
        main_model_requests=4,
        repair_model_requests=4,
        skill_routing_model_requests=4,
        temporary_agent_model_requests=4,
        verifier_model_requests=4,
        tool_calls=4,
        wall_time_milliseconds=60_000,
    )


def _journal(
    attestation: ArmRuntimeAttestation,
    events: Sequence[tuple[CellJournalEventKind, str]],
) -> list[CellJournalEntry]:
    entries: list[CellJournalEntry] = []
    for kind, payload_hash in events:
        entries.append(
            build_cell_journal_entry(
                attestation=attestation,
                event_kind=kind,
                payload_hash=payload_hash,
                previous_entry=entries[-1] if entries else None,
            )
        )
    return entries


def _cell_run(
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    cell_id: str,
    *,
    failed: bool = False,
    diagnostic: bool = False,
) -> tuple[CellRuntimeEvidenceBundle, list[CellJournalEntry], TerminalEnvelope]:
    attestation = build_arm_runtime_attestation(
        bridge=bridge,
        blinded_cell_id=cell_id,
        audit_raw_memory_plane_id=f"audit-raw:{cell_id}",
        controller_visible_memory_plane_id=f"controller:{cell_id}",
        audit_raw_manifest=f'{{"raw":"{cell_id}"}}'.encode(),
        controller_visible_manifest=f'{{"visible":"{cell_id}"}}'.encode(),
    )
    provider_reservation = build_budget_reservation(
        attestation=attestation,
        reservation_id=f"model:{cell_id}",
        operation_kind=BudgetOperationKind.MAIN_MODEL_REQUEST,
        maximum_wall_time_milliseconds=10_000,
    )
    request = f'{{"cell":"{cell_id}"}}'.encode()
    execution_mode = (
        ProviderExecutionMode.DIAGNOSTIC_DOUBLE
        if diagnostic
        else ProviderExecutionMode.LIVE_QWEN_PROVIDER
    )
    pre_call = build_provider_pre_call_anchor(
        attestation=attestation,
        reservation=provider_reservation,
        pre_call_id=f"precall:{cell_id}",
        execution_mode=execution_mode,
        model_name="diagnostic-double" if diagnostic else "qwen3.7-max",
        request_payload=request,
        provider_request_id=None if diagnostic else f"request:{cell_id}",
    )
    transport = None
    if not diagnostic:
        transport = build_external_transport_anchor(
            attestation=attestation,
            reservation=provider_reservation,
            pre_call=pre_call,
            adapter_id="openai-compatible-http-adapter-v3",
            request_payload=request,
            transport_metadata=f'{{"attempt":"{cell_id}"}}'.encode(),
            http_metadata=b'{"status":200}',
            raw_response_body=f'{{"id":"response:{cell_id}"}}'.encode(),
            http_status_code=200,
            provider_response_id=f"response:{cell_id}",
        )
    attempt = build_provider_attempt_receipt(
        attestation=attestation,
        attempt_id=f"attempt:{cell_id}",
        request_reservation=provider_reservation,
        pre_call=pre_call,
        status=(ProviderAttemptStatus.FAILED if failed else ProviderAttemptStatus.SUCCEEDED),
        request_payload=request,
        raw_visible_output=b'{"operator":"stop"}',
        raw_reasoning="先检查证据，再执行策略。".encode(),
        usage=b'{"prompt_tokens":20,"completion_tokens":12}',
        error=b'{"type":"shape_error"}' if failed else None,
        failure_phase=ProviderFailurePhase.RESPONSE_VALIDATION if failed else None,
        external_transport_anchor=transport,
    )
    mechanical_reservation = build_budget_reservation(
        attestation=attestation,
        reservation_id=f"mechanical:{cell_id}",
        operation_kind=BudgetOperationKind.MECHANICAL_TRANSITION,
        maximum_wall_time_milliseconds=1_000,
    )
    mechanical = build_mechanical_transition_receipt(
        bridge=bridge,
        attestation=attestation,
        walltime_reservation=mechanical_reservation,
        transition_id=f"stimuli:{cell_id}",
        input_state=b"before",
        challenge_fixture=f'{{"cell":"{cell_id}"}}'.encode(),
        output_state=b"after",
    )
    provider_settlement = build_budget_ledger_entry(
        reservation=provider_reservation,
        sequence=1,
        outcome=BudgetOutcome.FAILED if failed else BudgetOutcome.SUCCEEDED,
        actual_wall_time_milliseconds=800,
        evidence_receipt_hash=attempt.receipt_hash,
    )
    mechanical_settlement = build_budget_ledger_entry(
        reservation=mechanical_reservation,
        sequence=2,
        outcome=BudgetOutcome.SUCCEEDED,
        actual_wall_time_milliseconds=12,
        evidence_receipt_hash=mechanical.receipt_hash,
    )
    ledger = build_budget_ledger(
        attestation=attestation,
        budget_limit=_limit(),
        reservations=[provider_reservation, mechanical_reservation],
        settlements=[provider_settlement, mechanical_settlement],
    )
    evidence = build_cell_runtime_evidence_bundle(
        bridge=bridge,
        attestation=attestation,
        budget_ledger=ledger,
        provider_pre_calls=[pre_call],
        transport_anchors=[] if transport is None else [transport],
        provider_attempts=[attempt],
        mechanical_transitions=[mechanical],
    )
    events = [
        (CellJournalEventKind.ARM_ATTESTED, attestation.attestation_hash),
        (CellJournalEventKind.BUDGET_RESERVED, provider_reservation.reservation_hash),
        (CellJournalEventKind.PROVIDER_PRECALL_RECORDED, pre_call.pre_call_hash),
    ]
    if transport is not None:
        events.append(
            (
                CellJournalEventKind.TRANSPORT_ANCHOR_RECORDED,
                transport.transport_anchor_hash,
            )
        )
    events.extend(
        [
            (CellJournalEventKind.PROVIDER_ATTEMPT_RECORDED, attempt.receipt_hash),
            (CellJournalEventKind.BUDGET_SETTLED, provider_settlement.entry_hash),
            (
                CellJournalEventKind.BUDGET_RESERVED,
                mechanical_reservation.reservation_hash,
            ),
            (
                CellJournalEventKind.MECHANICAL_TRANSITION_RECORDED,
                mechanical.receipt_hash,
            ),
            (CellJournalEventKind.BUDGET_SETTLED, mechanical_settlement.entry_hash),
        ]
    )
    entries = _journal(attestation, events)
    terminal = build_terminal_envelope(
        bridge=bridge,
        entries=entries,
        runtime_evidence=evidence,
    )
    return evidence, entries, terminal


def _write_protocol_and_bridge(
    root: Path,
) -> tuple[AdaptiveLoopBenchmarkExecutionBundle, AdaptiveLoopBenchmarkReceiptBridge]:
    bundle = write_adaptive_loop_benchmark_execution_protocol(
        root,
        randomization_seed=27_132_026,
    )
    bridge = write_adaptive_loop_benchmark_receipt_bridge_once(root, bundle)
    return bundle, bridge


def _write_cell(
    root: Path,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    cell_id: str,
    *,
    failed: bool = False,
) -> TerminalEnvelope:
    evidence, entries, terminal = _cell_run(bridge, cell_id, failed=failed)
    write_cell_runtime_evidence_once(root, bridge, evidence)
    for entry in entries:
        write_cell_journal_entry_once(root, bridge, entry)
    write_terminal_envelope_once(root, bridge, terminal)
    return terminal


def test_v3_bridge_binds_all_protocol_artifacts_and_240_runner_cells() -> None:
    bundle = _bundle()
    bridge = build_adaptive_loop_benchmark_receipt_bridge(bundle)

    assert len(bridge.cells) == 240
    assert [item.blinded_cell_id for item in bridge.cells] == [
        item.blinded_cell_id for item in bundle.blinded_cells.cells
    ]
    assert {item.arm for item in bridge.cells} == set(AdaptiveLoopBenchmarkArm)
    for cell in bridge.cells:
        assert (
            cell.parent_v1_protocol_hash,
            cell.execution_protocol_hash,
            cell.public_scenario_panel_hash,
            cell.blinded_manifest_hash,
            cell.runner_assignment_manifest_hash,
            cell.private_scoring_manifest_hash,
        ) == (
            bridge.parent_v1_protocol_hash,
            bridge.execution_protocol_hash,
            bridge.public_scenario_panel_hash,
            bridge.blinded_manifest_hash,
            bridge.runner_assignment_manifest_hash,
            bridge.private_scoring_manifest_hash,
        )
        assert cell.runner_only_assignment is True


def test_old_v1_seed_repeat_receipt_cannot_downgrade_v3() -> None:
    old_binding = {
        "schema_version": "adaptive-loop-arm-runtime-attestation-v1",
        "protocol_hash": canonical_sha256({"old": "v1"}),
        "cell_id": "cell:empty_tool_result:11",
        "challenge_kind": "empty_tool_result",
        "random_seed": 11,
        "arm": "adaptive_sovereign",
        "trajectory_id": "trajectory:old",
    }
    with pytest.raises(ValidationError):
        ArmRuntimeAttestation.model_validate(old_binding)
    with pytest.raises(ValidationError):
        AdaptiveLoopBenchmarkCellExecutionBinding.model_validate(old_binding)


def test_bridge_hash_and_runner_arm_tampering_fail_closed() -> None:
    bridge = _bridge()
    changed = bridge.model_dump(mode="json")
    cell = changed["cells"][0]
    cell["arm"] = (
        AdaptiveLoopBenchmarkArm.FIXED_PIPELINE.value
        if cell["arm"] != AdaptiveLoopBenchmarkArm.FIXED_PIPELINE.value
        else AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN.value
    )
    cell["cell_binding_hash"] = canonical_sha256(
        {key: value for key, value in cell.items() if key != "cell_binding_hash"}
    )
    changed["receipt_bridge_hash"] = canonical_sha256(
        {key: value for key, value in changed.items() if key != "receipt_bridge_hash"}
    )
    with pytest.raises(ValidationError, match="runner-only assignment"):
        AdaptiveLoopBenchmarkReceiptBridge.model_validate(changed)


@pytest.mark.parametrize("arm", list(AdaptiveLoopBenchmarkArm))
def test_runtime_attestation_uses_exact_four_arm_profile_and_separate_memory(
    arm: AdaptiveLoopBenchmarkArm,
) -> None:
    bridge = _bridge()
    cell = next(item for item in bridge.cells if item.arm is arm)
    attestation = build_arm_runtime_attestation(
        bridge=bridge,
        blinded_cell_id=cell.blinded_cell_id,
        audit_raw_memory_plane_id=f"raw:{arm.value}",
        controller_visible_memory_plane_id=f"visible:{arm.value}",
        audit_raw_manifest=f"raw-{arm.value}".encode(),
        controller_visible_manifest=f"visible-{arm.value}".encode(),
    )
    assert attestation.capability_profile.arm is arm
    assert attestation.cell_binding == cell
    assert attestation.audit_raw_manifest_sha256 != (attestation.controller_visible_manifest_sha256)

    aliased = attestation.model_dump(mode="json")
    aliased["controller_visible_memory_plane_id"] = aliased["audit_raw_memory_plane_id"]
    aliased["attestation_hash"] = canonical_sha256(
        {key: value for key, value in aliased.items() if key != "attestation_hash"}
    )
    with pytest.raises(ValidationError, match="must be separate"):
        ArmRuntimeAttestation.model_validate(aliased)


def test_provider_precall_transport_and_diagnostic_tracks_are_disjoint_but_nonformal() -> None:
    bridge = _bridge()
    cell_id = bridge.cells[0].blinded_cell_id
    live, _, terminal = _cell_run(bridge, cell_id)
    attempt = live.provider_attempts[0]
    assert attempt.formal_eligible is False
    assert attempt.external_transport_anchor is not None
    assert attempt.external_transport_anchor.process_local_only is True
    assert attempt.external_transport_anchor.external_process_or_service_boundary_crossed is False
    assert attempt.external_transport_anchor.independent_external_signature_verified is False
    assert attempt.external_transport_anchor.formal_eligible is False
    assert attempt.provider_model_and_ids_are_unverified_metadata is True
    assert attempt.independent_external_signature_verified is False
    assert attempt.raw_provider_response_body_sha256 is not None
    assert attempt.raw_visible_output_sha256 is not None
    assert attempt.raw_reasoning_sha256 is not None
    assert attempt.usage_sha256 is not None
    assert terminal.formal_eligible is False
    assert terminal.process_local_transport_integrity_only is True
    assert terminal.independently_signed_transport_gateway_verified is False

    diagnostic, _, diagnostic_terminal = _cell_run(
        bridge,
        cell_id,
        diagnostic=True,
    )
    diagnostic_attempt = diagnostic.provider_attempts[0]
    assert diagnostic_attempt.formal_eligible is False
    assert diagnostic_attempt.external_transport_anchor is None
    assert diagnostic_terminal.formal_eligible is False

    fake = diagnostic_attempt.model_dump(mode="json")
    fake["provider_name"] = "qwen"
    fake["model_name"] = "qwen3.7-max"
    fake["formal_eligible"] = True
    fake["receipt_hash"] = canonical_sha256(
        {key: value for key, value in fake.items() if key != "receipt_hash"}
    )
    with pytest.raises(ValidationError, match="formal_eligible"):
        ProviderAttemptReceipt.model_validate(fake)


@pytest.mark.parametrize(
    ("model_name", "adapter_id", "http_status_code"),
    [
        ("qwen3.7-max", "openai-compatible-http-adapter-v3", 200),
        ("qwen-self-reported-only", "arbitrary-in-process-adapter", 418),
        ("qwen-model-metadata", "bytes-never-sent-to-network", 599),
    ],
)
def test_arbitrary_process_local_bytes_http_and_adapter_never_establish_formal_identity(
    model_name: str,
    adapter_id: str,
    http_status_code: int,
) -> None:
    bridge = _bridge()
    cell = bridge.cells[0]
    attestation = build_arm_runtime_attestation(
        bridge=bridge,
        blinded_cell_id=cell.blinded_cell_id,
        audit_raw_memory_plane_id="raw:process-local",
        controller_visible_memory_plane_id="visible:process-local",
        audit_raw_manifest=b"raw-process-local",
        controller_visible_manifest=b"visible-process-local",
    )
    reservation = build_budget_reservation(
        attestation=attestation,
        reservation_id="model:process-local",
        operation_kind=BudgetOperationKind.MAIN_MODEL_REQUEST,
        maximum_wall_time_milliseconds=1_000,
    )
    request = b"arbitrary bytes that were never sent to a network"
    pre_call = build_provider_pre_call_anchor(
        attestation=attestation,
        reservation=reservation,
        pre_call_id="precall:process-local",
        execution_mode=ProviderExecutionMode.LIVE_QWEN_PROVIDER,
        model_name=model_name,
        request_payload=request,
        provider_request_id="self-reported-request-id",
    )
    anchor = build_external_transport_anchor(
        attestation=attestation,
        reservation=reservation,
        pre_call=pre_call,
        adapter_id=adapter_id,
        request_payload=request,
        transport_metadata=b"self-consistent hand-made trace",
        http_metadata=f'{{"status":{http_status_code}}}'.encode(),
        raw_response_body=b'{"id":"self-reported-response-id"}',
        http_status_code=http_status_code,
        provider_response_id="self-reported-response-id",
    )
    attempt = build_provider_attempt_receipt(
        attestation=attestation,
        attempt_id="attempt:process-local",
        request_reservation=reservation,
        pre_call=pre_call,
        status=ProviderAttemptStatus.SUCCEEDED,
        request_payload=request,
        raw_visible_output=b'{"operator":"stop"}',
        raw_reasoning=b"self-reported reasoning",
        usage=b'{"completion_tokens":1}',
        error=None,
        external_transport_anchor=anchor,
    )

    assert pre_call.provider_model_and_request_id_are_unverified_metadata is True
    assert anchor.process_local_only is True
    assert anchor.external_process_or_service_boundary_crossed is False
    assert anchor.independent_external_signature_verified is False
    assert anchor.provider_model_and_ids_are_unverified_metadata is True
    assert anchor.formal_eligible is False
    assert attempt.formal_eligible is False


def test_handmade_transport_and_old_v3_formal_claims_fail_closed() -> None:
    bridge = _bridge()
    evidence, _, terminal = _cell_run(bridge, bridge.cells[0].blinded_cell_id)
    anchor = evidence.transport_anchors[0]
    attempt = evidence.provider_attempts[0]

    old_v3_anchor = anchor.model_dump(mode="json")
    for new_field in (
        "process_local_only",
        "independent_external_signature_verified",
        "provider_model_and_ids_are_unverified_metadata",
        "formal_eligible",
    ):
        old_v3_anchor.pop(new_field)
    old_v3_anchor["external_process_or_service_boundary_crossed"] = True
    old_v3_anchor["transport_anchor_hash"] = canonical_sha256(
        {key: value for key, value in old_v3_anchor.items() if key != "transport_anchor_hash"}
    )
    with pytest.raises(ValidationError):
        ExternalTransportAnchor.model_validate(old_v3_anchor)

    old_formal_attempt = attempt.model_dump(mode="json")
    old_formal_attempt.pop("provider_model_and_ids_are_unverified_metadata")
    old_formal_attempt.pop("independent_external_signature_verified")
    old_formal_attempt["external_transport_anchor"] = old_v3_anchor
    old_formal_attempt["formal_eligible"] = True
    old_formal_attempt["receipt_hash"] = canonical_sha256(
        {key: value for key, value in old_formal_attempt.items() if key != "receipt_hash"}
    )
    with pytest.raises(ValidationError, match="formal_eligible"):
        ProviderAttemptReceipt.model_validate(old_formal_attempt)

    old_formal_terminal = terminal.model_dump(mode="json")
    old_formal_terminal.pop("process_local_transport_integrity_only")
    old_formal_terminal.pop("independently_signed_transport_gateway_verified")
    old_formal_terminal["formal_eligible"] = True
    old_formal_terminal["terminal_hash"] = canonical_sha256(
        {key: value for key, value in old_formal_terminal.items() if key != "terminal_hash"}
    )
    with pytest.raises(ValidationError, match="formal_eligible"):
        TerminalEnvelope.model_validate(old_formal_terminal)


def test_model_metadata_mismatch_cannot_be_hidden_by_self_consistent_transport_hash() -> None:
    bridge = _bridge()
    evidence, _, _ = _cell_run(bridge, bridge.cells[0].blinded_cell_id)
    attestation = evidence.arm_attestation
    reservation = evidence.budget_ledger.reservations[0]
    pre_call = evidence.provider_pre_calls[0]
    anchor_payload = evidence.transport_anchors[0].model_dump(mode="json")
    anchor_payload["model_name"] = "qwen-different-self-report"
    anchor_payload["transport_anchor_hash"] = canonical_sha256(
        {key: value for key, value in anchor_payload.items() if key != "transport_anchor_hash"}
    )
    mismatched_anchor = ExternalTransportAnchor.model_validate(anchor_payload)

    with pytest.raises(ValidationError, match="disagrees with transport anchor"):
        build_provider_attempt_receipt(
            attestation=attestation,
            attempt_id="attempt:mismatched-model-metadata",
            request_reservation=reservation,
            pre_call=pre_call,
            status=ProviderAttemptStatus.SUCCEEDED,
            request_payload=f'{{"cell":"{attestation.cell_binding.blinded_cell_id}"}}'.encode(),
            raw_visible_output=b'{"operator":"stop"}',
            raw_reasoning=b"reasoning",
            usage=b'{"completion_tokens":1}',
            error=None,
            external_transport_anchor=mismatched_anchor,
        )


def test_preflight_failure_is_recorded_nonformal_and_started_failure_is_charged() -> None:
    bridge = _bridge()
    cell_id = bridge.cells[0].blinded_cell_id
    evidence, _, terminal = _cell_run(bridge, cell_id, failed=True)
    attempt = evidence.provider_attempts[0]
    settlement = evidence.budget_ledger.settlements[0]
    assert attempt.status is ProviderAttemptStatus.FAILED
    assert attempt.error_sha256 is not None
    assert settlement.outcome is BudgetOutcome.FAILED
    assert settlement.charged.main_model_requests == 1
    assert evidence.budget_ledger.declared_failed_charged_total.main_model_requests == 1
    assert terminal.runtime_failure_recorded is True

    hidden = settlement.model_dump(mode="json")
    hidden["charged"]["main_model_requests"] = 0
    hidden["entry_hash"] = canonical_sha256(
        {key: value for key, value in hidden.items() if key != "entry_hash"}
    )
    hidden_entry = BudgetLedgerEntry.model_validate(hidden)
    ledger = evidence.budget_ledger.model_dump(mode="json")
    ledger["settlements"][0] = hidden_entry.model_dump(mode="json")
    ledger["declared_charged_total"]["main_model_requests"] = 0
    ledger["declared_failed_charged_total"]["main_model_requests"] = 0
    ledger["ledger_hash"] = canonical_sha256(
        {key: value for key, value in ledger.items() if key != "ledger_hash"}
    )
    with pytest.raises(ValidationError, match="hides or invents"):
        BudgetLedger.model_validate(ledger)


@pytest.mark.parametrize(
    ("operation_kind", "charged_field"),
    [
        (BudgetOperationKind.MAIN_MODEL_REQUEST, "main_model_requests"),
        (BudgetOperationKind.REPAIR_MODEL_REQUEST, "repair_model_requests"),
        (BudgetOperationKind.SKILL_ROUTING_MODEL_REQUEST, "skill_routing_model_requests"),
        (
            BudgetOperationKind.TEMPORARY_AGENT_MODEL_REQUEST,
            "temporary_agent_model_requests",
        ),
        (BudgetOperationKind.VERIFIER_MODEL_REQUEST, "verifier_model_requests"),
        (BudgetOperationKind.TOOL_CALL, "tool_calls"),
        (BudgetOperationKind.MECHANICAL_TRANSITION, None),
    ],
)
def test_all_budget_lanes_share_failure_accounting(
    operation_kind: BudgetOperationKind,
    charged_field: str | None,
) -> None:
    bridge = _bridge()
    cell = bridge.cells[0]
    attestation = build_arm_runtime_attestation(
        bridge=bridge,
        blinded_cell_id=cell.blinded_cell_id,
        audit_raw_memory_plane_id="raw:test",
        controller_visible_memory_plane_id="visible:test",
        audit_raw_manifest=b"raw",
        controller_visible_manifest=b"visible",
    )
    reservation = build_budget_reservation(
        attestation=attestation,
        reservation_id=f"reservation:{operation_kind.value}",
        operation_kind=operation_kind,
        maximum_wall_time_milliseconds=1_000,
    )
    settlement = build_budget_ledger_entry(
        reservation=reservation,
        sequence=1,
        outcome=BudgetOutcome.FAILED,
        actual_wall_time_milliseconds=17,
        evidence_receipt_hash=canonical_sha256({"failed": operation_kind.value}),
    )
    for field_name in (
        "main_model_requests",
        "repair_model_requests",
        "skill_routing_model_requests",
        "temporary_agent_model_requests",
        "verifier_model_requests",
        "tool_calls",
    ):
        assert getattr(settlement.charged, field_name) == (1 if field_name == charged_field else 0)


def test_mechanical_transition_is_exact_public_scenario_and_never_qwen_evidence() -> None:
    bridge = _bridge()
    evidence, _, _ = _cell_run(bridge, bridge.cells[0].blinded_cell_id)
    receipt = evidence.mechanical_transitions[0]
    assert len(receipt.public_stimulus_hashes) == 12
    assert receipt.model_request_count == 0
    assert receipt.network_request_count == 0
    assert receipt.formal_provider_eligible is False
    assert receipt.scientific_evidence_established is False
    with pytest.raises(ValidationError):
        ProviderAttemptReceipt.model_validate(receipt.model_dump(mode="json"))

    forged = receipt.model_dump(mode="json")
    forged["model_request_count"] = 1
    forged["scientific_evidence_established"] = True
    forged["receipt_hash"] = canonical_sha256(
        {key: value for key, value in forged.items() if key != "receipt_hash"}
    )
    with pytest.raises(ValidationError):
        MechanicalChallengeTransitionReceipt.model_validate(forged)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda entries: [entries[0], *entries[2:]],
        lambda entries: [entries[1], entries[0], *entries[2:]],
        lambda entries: [entries[0], entries[1], entries[1], *entries[2:]],
    ],
    ids=["deleted", "reordered", "inserted"],
)
def test_replay_rejects_deleted_reordered_or_inserted_journal(
    mutate: Any,
) -> None:
    bridge = _bridge()
    evidence, entries, _ = _cell_run(bridge, bridge.cells[0].blinded_cell_id)
    with pytest.raises(AdaptiveLoopBenchmarkReceiptError):
        replay_cell_journal(
            bridge=bridge,
            entries=mutate(entries),
            runtime_evidence=evidence,
        )


def test_fixed_paths_write_once_and_cross_cell_substitution_fail_closed(
    tmp_path: Path,
) -> None:
    _, bridge = _write_protocol_and_bridge(tmp_path)
    first, second = bridge.cells[:2]
    evidence, entries, terminal = _cell_run(bridge, first.blinded_cell_id)
    write_cell_runtime_evidence_once(tmp_path, bridge, evidence)
    for entry in entries:
        write_cell_journal_entry_once(tmp_path, bridge, entry)
    write_terminal_envelope_once(tmp_path, bridge, terminal)
    assert load_adaptive_loop_benchmark_receipt_bridge(tmp_path) == bridge
    assert load_cell_journal_entries(tmp_path, bridge, first.blinded_cell_id) == entries

    changed = entries[0].model_dump(mode="json")
    changed["cell_binding"] = second.model_dump(mode="json")
    changed["trajectory_id"] = f"trajectory-v3:{second.cell_binding_hash}"
    changed["entry_hash"] = canonical_sha256(
        {key: value for key, value in changed.items() if key != "entry_hash"}
    )
    cross_cell = CellJournalEntry.model_validate(changed)
    with pytest.raises(AdaptiveLoopBenchmarkReceiptError):
        write_cell_journal_entry_once(tmp_path, bridge, cross_cell)

    different_bundle = build_adaptive_loop_benchmark_execution_bundle(randomization_seed=99)
    with pytest.raises(AdaptiveLoopBenchmarkReceiptError, match="fixed-path"):
        write_adaptive_loop_benchmark_receipt_bridge_once(
            tmp_path,
            different_bundle,
        )


def test_runtime_artifacts_do_not_expose_private_scoring_values() -> None:
    bridge = _bridge()
    evidence, entries, terminal = _cell_run(bridge, bridge.cells[0].blinded_cell_id)
    runtime_text = "\n".join(
        [
            canonical_json(bridge),
            canonical_json(evidence),
            *(canonical_json(item) for item in entries),
            canonical_json(terminal),
        ]
    )
    for forbidden in (
        '"expected_terminal_state"',
        '"required_public_fact_ids"',
        '"forbidden_as_current_fact_ids"',
        '"required_terminal_tokens"',
        '"forbidden_terminal_tokens"',
        '"oracles"',
    ):
        assert forbidden not in runtime_text
    assert '"private_scoring_manifest_hash"' in runtime_text


def test_reveal_fails_before_all_240_terminals_and_before_scoring_load(
    tmp_path: Path,
) -> None:
    _, bridge = _write_protocol_and_bridge(tmp_path)
    _write_cell(tmp_path, bridge, bridge.cells[0].blinded_cell_id)
    scoring_path = (
        tmp_path / "runner-only" / "adaptive-loop-benchmark-hidden-oracle-manifest-v3.json"
    )
    scoring_path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(AdaptiveLoopBenchmarkReceiptError, match="missing"):
        build_blind_reveal_package(tmp_path, bridge)
    with pytest.raises(AdaptiveLoopBenchmarkReceiptError, match="240-cell set"):
        write_benchmark_terminal_set_seal_once(tmp_path, bridge)


def test_full_240_cell_seal_then_reveal_creates_inputs_but_no_results(
    tmp_path: Path,
) -> None:
    bundle, bridge = _write_protocol_and_bridge(tmp_path)
    terminals = [
        _write_cell(
            tmp_path,
            bridge,
            cell.blinded_cell_id,
            failed=(index == 0),
        )
        for index, cell in enumerate(bridge.cells)
    ]
    seal = write_benchmark_terminal_set_seal_once(tmp_path, bridge)
    package = write_blind_reveal_package_once(tmp_path, bridge)

    assert len(seal.commitments) == 240
    assert len(package.score_input.cells) == 240
    assert package.authorization.terminal_set_hash == seal.terminal_set_hash
    assert package.score_input.private_scoring_manifest_hash == (
        bundle.runner_only_scoring.hidden_oracle_manifest_hash
    )
    assert package.score_input.scoring_not_executed is True
    assert package.score_input.scientific_result_generated is False
    assert terminals[0].runtime_failure_recorded is True
    assert terminals[0].formal_eligible is False

    serialized = canonical_json(package.score_input)
    assert '"score"' not in serialized
    assert '"result"' not in serialized
    assert '"expected_terminal_state"' in serialized


def test_contract_hash_tampering_and_extra_fields_are_rejected() -> None:
    bridge = _bridge()
    evidence, _, terminal = _cell_run(bridge, bridge.cells[0].blinded_cell_id)
    changed = terminal.model_dump(mode="json")
    changed["runtime_evidence_hash"] = canonical_sha256({"wrong": True})
    with pytest.raises(ValidationError, match="hash mismatch"):
        TerminalEnvelope.model_validate(changed)

    pre_call = evidence.provider_pre_calls[0].model_dump(mode="json")
    pre_call["provider_api_key"] = "must-never-be-stored"
    with pytest.raises(ValidationError):
        ProviderPreCallAnchor.model_validate(pre_call)

    transport = evidence.transport_anchors[0].model_dump(mode="json")
    transport["transport_anchor_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="hash mismatch"):
        ExternalTransportAnchor.model_validate(transport)

    runtime = evidence.model_dump(mode="json")
    runtime["hidden_oracle"] = {"leak": True}
    with pytest.raises(ValidationError):
        CellRuntimeEvidenceBundle.model_validate(runtime)


def test_bridge_json_round_trip_is_canonical() -> None:
    bridge = _bridge()
    payload = json.loads(canonical_json(bridge))
    assert AdaptiveLoopBenchmarkReceiptBridge.model_validate(payload) == bridge
