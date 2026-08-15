"""Immutable v3 execution receipts for the adaptive-loop benchmark.

The contracts in this module record and replay execution evidence.  They never
call a model, run a tool, score a scientific answer, or manufacture a research
result.  The current transport receipt is deliberately only a process-local
integrity commitment.  It cannot establish provider/model identity or formal
execution eligibility until a separately operated, independently signed
transport gateway is implemented.  The 240-cell v3 execution protocol and
post-seal reveal barrier remain bound, while obsolete v1 and formerly formal
v3 runtime artifacts fail closed.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.research.adaptive_loop_benchmark import (
    AdaptiveLoopBenchmarkArm,
    AdaptiveLoopBenchmarkArmSpec,
    AdaptiveLoopChallengeKind,
    build_adaptive_loop_benchmark_protocol,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkBlindedCellManifest,
    AdaptiveLoopBenchmarkExecutionBundle,
    AdaptiveLoopBenchmarkExecutionProtocol,
    AdaptiveLoopBenchmarkHiddenOracleManifest,
    AdaptiveLoopBenchmarkMachineOracle,
    AdaptiveLoopBenchmarkPublicScenario,
    AdaptiveLoopBenchmarkRunnerAssignmentManifest,
)


class AdaptiveLoopBenchmarkReceiptError(RuntimeError):
    """Raised when immutable benchmark evidence fails closed."""


class ProviderExecutionMode(str, Enum):
    """Declared live-Qwen and diagnostic execution are disjoint tracks."""

    LIVE_QWEN_PROVIDER = "live_qwen_provider"
    DIAGNOSTIC_DOUBLE = "diagnostic_double"


class ProviderAttemptStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProviderFailurePhase(str, Enum):
    PREFLIGHT = "preflight"
    TRANSPORT = "transport"
    HTTP = "http"
    PROVIDER = "provider"
    RESPONSE_VALIDATION = "response_validation"


class BudgetOperationKind(str, Enum):
    MAIN_MODEL_REQUEST = "main_model_request"
    REPAIR_MODEL_REQUEST = "repair_model_request"
    SKILL_ROUTING_MODEL_REQUEST = "skill_routing_model_request"
    TEMPORARY_AGENT_MODEL_REQUEST = "temporary_agent_model_request"
    VERIFIER_MODEL_REQUEST = "verifier_model_request"
    TOOL_CALL = "tool_call"
    MECHANICAL_TRANSITION = "mechanical_transition"


class BudgetOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED_BEFORE_START = "cancelled_before_start"


class CellJournalEventKind(str, Enum):
    ARM_ATTESTED = "arm_attested"
    BUDGET_RESERVED = "budget_reserved"
    PROVIDER_PRECALL_RECORDED = "provider_precall_recorded"
    TRANSPORT_ANCHOR_RECORDED = "transport_anchor_recorded"
    PROVIDER_ATTEMPT_RECORDED = "provider_attempt_recorded"
    MECHANICAL_TRANSITION_RECORDED = "mechanical_transition_recorded"
    BUDGET_SETTLED = "budget_settled"


_MODEL_OPERATION_FIELDS: dict[BudgetOperationKind, str] = {
    BudgetOperationKind.MAIN_MODEL_REQUEST: "main_model_requests",
    BudgetOperationKind.REPAIR_MODEL_REQUEST: "repair_model_requests",
    BudgetOperationKind.SKILL_ROUTING_MODEL_REQUEST: "skill_routing_model_requests",
    BudgetOperationKind.TEMPORARY_AGENT_MODEL_REQUEST: ("temporary_agent_model_requests"),
    BudgetOperationKind.VERIFIER_MODEL_REQUEST: "verifier_model_requests",
}
_COUNT_FIELDS = (
    "main_model_requests",
    "repair_model_requests",
    "skill_routing_model_requests",
    "temporary_agent_model_requests",
    "verifier_model_requests",
    "tool_calls",
)
_CELL_ID_PATTERN = re.compile(r"^cell-[0-9a-f]{32}$")
_PUBLIC_PROTOCOL_FILENAME = "adaptive-loop-benchmark-execution-protocol-v3.json"
_BLINDED_MANIFEST_FILENAME = "adaptive-loop-benchmark-blinded-cell-manifest-v3.json"
_RUNNER_MANIFEST_FILENAME = "adaptive-loop-benchmark-runner-assignment-manifest-v3.json"
_SCORING_MANIFEST_FILENAME = "adaptive-loop-benchmark-hidden-oracle-manifest-v3.json"
_BRIDGE_FILENAME = "adaptive-loop-benchmark-receipt-bridge-v3.json"
_RUNTIME_BUNDLE_FILENAME = "runtime-evidence-bundle-v3.json"
_TERMINAL_FILENAME = "terminal-envelope-v3.json"
_TERMINAL_SET_FILENAME = "terminal-set-seal-v3.json"
_REVEAL_AUTH_FILENAME = "reveal-authorization-v3.json"
_SCORE_INPUT_FILENAME = "evaluator-score-input-v3.json"


class AdaptiveLoopBenchmarkCellExecutionBinding(KernelContract):
    """One runner-only v3 identity leaf for an independent scenario/arm cell."""

    schema_version: Literal["adaptive-loop-cell-execution-binding-v3"] = (
        "adaptive-loop-cell-execution-binding-v3"
    )
    parent_v1_protocol_hash: Sha256
    execution_protocol_hash: Sha256
    public_scenario_panel_hash: Sha256
    blinded_manifest_hash: Sha256
    runner_assignment_manifest_hash: Sha256
    private_scoring_manifest_hash: Sha256
    blinded_cell_id: StableId
    scenario_id: StableId
    challenge_kind: AdaptiveLoopChallengeKind
    public_scenario_hash: Sha256
    run_position: int = Field(ge=1, le=4)
    model_draw_ordinal: Literal[1] = 1
    sequence_id: StableId
    arm: AdaptiveLoopBenchmarkArm
    runner_only_assignment: Literal[True] = True
    hidden_scoring_values_absent: Literal[True] = True
    cell_binding_hash: Sha256

    @field_validator("blinded_cell_id")
    @classmethod
    def _validate_cell_id(cls, value: str) -> str:
        if _CELL_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("v3 blinded cell ID has an invalid form")
        return value

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkCellExecutionBinding:
        if self.cell_binding_hash != _calculated_hash(self, "cell_binding_hash"):
            raise ValueError("v3 cell binding hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkCellExecutionBinding:
        return cls.model_validate(_addressed(values, "cell_binding_hash"))


class AdaptiveLoopBenchmarkReceiptBridge(KernelContract):
    """Runner-only bridge from official v3 protocol artifacts to receipt cells."""

    schema_version: Literal["adaptive-loop-benchmark-receipt-bridge-v3"] = (
        "adaptive-loop-benchmark-receipt-bridge-v3"
    )
    parent_v1_protocol_hash: Sha256
    execution_protocol_hash: Sha256
    public_scenario_panel_hash: Sha256
    blinded_manifest_hash: Sha256
    runner_assignment_manifest_hash: Sha256
    private_scoring_manifest_hash: Sha256
    execution_protocol: AdaptiveLoopBenchmarkExecutionProtocol
    blinded_manifest: AdaptiveLoopBenchmarkBlindedCellManifest
    runner_assignment_manifest: AdaptiveLoopBenchmarkRunnerAssignmentManifest
    cells: list[AdaptiveLoopBenchmarkCellExecutionBinding] = Field(
        min_length=240,
        max_length=240,
    )
    runner_only: Literal[True] = True
    controller_access_allowed: Literal[False] = False
    blinded_evaluator_access_before_reveal_allowed: Literal[False] = False
    hidden_scoring_values_absent: Literal[True] = True
    v1_seed_repeat_identity_formally_eligible: Literal[False] = False
    receipt_bridge_hash: Sha256

    @model_validator(mode="after")
    def _validate_bridge(self) -> AdaptiveLoopBenchmarkReceiptBridge:
        protocol = self.execution_protocol
        blinded = self.blinded_manifest
        runner = self.runner_assignment_manifest
        common = (
            self.parent_v1_protocol_hash,
            self.execution_protocol_hash,
            self.public_scenario_panel_hash,
            self.blinded_manifest_hash,
            self.runner_assignment_manifest_hash,
            self.private_scoring_manifest_hash,
        )
        expected_common = (
            protocol.parent_v1_protocol_hash,
            protocol.execution_protocol_hash,
            protocol.public_scenario_panel_hash,
            blinded.blinded_manifest_hash,
            runner.runner_assignment_manifest_hash,
            protocol.private_scoring_manifest_hash,
        )
        if common != expected_common:
            raise ValueError("receipt bridge top-level v3 hashes disagree")
        if protocol.blinded_manifest_hash != blinded.blinded_manifest_hash:
            raise ValueError("receipt bridge does not bind the blinded manifest")
        if protocol.runner_assignment_manifest_hash != runner.runner_assignment_manifest_hash:
            raise ValueError("receipt bridge does not bind the runner manifest")
        if runner.blinded_manifest_hash != blinded.blinded_manifest_hash:
            raise ValueError("runner assignment does not bind the blinded manifest")
        if runner.private_scoring_manifest_hash != protocol.private_scoring_manifest_hash:
            raise ValueError("runner assignment does not bind private scoring")
        if blinded.parent_v1_protocol_hash != protocol.parent_v1_protocol_hash:
            raise ValueError("blinded manifest parent v1 hash mismatch")
        if runner.parent_v1_protocol_hash != protocol.parent_v1_protocol_hash:
            raise ValueError("runner manifest parent v1 hash mismatch")

        blinded_by_id = {item.blinded_cell_id: item for item in blinded.cells}
        assignment_by_id = {item.blinded_cell_id: item for item in runner.assignments}
        if set(blinded_by_id) != set(assignment_by_id):
            raise ValueError("bridge blinded and runner cell sets disagree")
        if [item.blinded_cell_id for item in self.cells] != [
            item.blinded_cell_id for item in blinded.cells
        ]:
            raise ValueError("bridge cell order is not the official blinded order")
        if len({item.cell_binding_hash for item in self.cells}) != 240:
            raise ValueError("bridge cell binding hashes must be unique")
        expected_prefix = common
        for cell in self.cells:
            blinded_cell = blinded_by_id.get(cell.blinded_cell_id)
            assignment = assignment_by_id.get(cell.blinded_cell_id)
            if blinded_cell is None or assignment is None:
                raise ValueError("bridge contains an unknown cell")
            if (
                cell.parent_v1_protocol_hash,
                cell.execution_protocol_hash,
                cell.public_scenario_panel_hash,
                cell.blinded_manifest_hash,
                cell.runner_assignment_manifest_hash,
                cell.private_scoring_manifest_hash,
            ) != expected_prefix:
                raise ValueError("cell does not bind every official v3 artifact hash")
            if (
                cell.scenario_id,
                cell.challenge_kind,
                cell.public_scenario_hash,
                cell.run_position,
                cell.model_draw_ordinal,
            ) != (
                blinded_cell.scenario_id,
                blinded_cell.challenge_kind,
                blinded_cell.public_scenario_hash,
                blinded_cell.run_position,
                blinded_cell.model_draw_ordinal,
            ):
                raise ValueError("cell does not match the blinded manifest")
            if (
                cell.scenario_id,
                cell.challenge_kind,
                cell.run_position,
                cell.model_draw_ordinal,
                cell.sequence_id,
                cell.arm,
            ) != (
                assignment.scenario_id,
                assignment.challenge_kind,
                assignment.run_position,
                assignment.model_draw_ordinal,
                assignment.sequence_id,
                assignment.arm,
            ):
                raise ValueError("cell does not match its runner-only assignment")
        if self.receipt_bridge_hash != _calculated_hash(self, "receipt_bridge_hash"):
            raise ValueError("receipt bridge hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkReceiptBridge:
        return cls.model_validate(_addressed(values, "receipt_bridge_hash"))

    def cell(self, blinded_cell_id: str) -> AdaptiveLoopBenchmarkCellExecutionBinding:
        for item in self.cells:
            if item.blinded_cell_id == blinded_cell_id:
                return item
        raise AdaptiveLoopBenchmarkReceiptError(
            f"cell {blinded_cell_id!r} is not in the v3 receipt bridge"
        )


class BudgetVector(KernelContract):
    """One accounting vector shared by every operation lane."""

    main_model_requests: int = Field(default=0, ge=0)
    repair_model_requests: int = Field(default=0, ge=0)
    skill_routing_model_requests: int = Field(default=0, ge=0)
    temporary_agent_model_requests: int = Field(default=0, ge=0)
    verifier_model_requests: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    wall_time_milliseconds: int = Field(default=0, ge=0)

    def add(self, other: BudgetVector) -> BudgetVector:
        return BudgetVector(
            **{
                name: int(getattr(self, name)) + int(getattr(other, name))
                for name in (*_COUNT_FIELDS, "wall_time_milliseconds")
            }
        )

    def exceeds(self, other: BudgetVector) -> bool:
        return any(
            int(getattr(self, name)) > int(getattr(other, name))
            for name in (*_COUNT_FIELDS, "wall_time_milliseconds")
        )


class ArmRuntimeAttestation(KernelContract):
    """Exact four-arm capability and separated-memory runtime attestation."""

    schema_version: Literal["adaptive-loop-arm-runtime-attestation-v3"] = (
        "adaptive-loop-arm-runtime-attestation-v3"
    )
    receipt_kind: Literal["arm_runtime_attestation"] = "arm_runtime_attestation"
    receipt_bridge_hash: Sha256
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    capability_profile: AdaptiveLoopBenchmarkArmSpec
    audit_raw_memory_plane_id: StableId
    controller_visible_memory_plane_id: StableId
    audit_raw_manifest_sha256: Sha256
    controller_visible_manifest_sha256: Sha256
    audit_raw_plane_excluded_from_controller_context: Literal[True] = True
    controller_visible_plane_cannot_mutate_audit_raw: Literal[True] = True
    arm_switch_after_trajectory_start_allowed: Literal[False] = False
    attestation_hash: Sha256

    @model_validator(mode="after")
    def _validate_attestation(self) -> ArmRuntimeAttestation:
        if self.trajectory_id != _trajectory_id(self.cell_binding):
            raise ValueError("trajectory binding prevents switching cell or arm")
        if self.capability_profile.arm is not self.cell_binding.arm:
            raise ValueError("capability profile arm differs from runner assignment")
        expected = _frozen_arm_profile(self.cell_binding.arm)
        if self.capability_profile != expected:
            raise ValueError("runtime capabilities differ from the frozen arm profile")
        if self.audit_raw_memory_plane_id == self.controller_visible_memory_plane_id:
            raise ValueError("audit raw and controller-visible memory planes must be separate")
        if self.audit_raw_manifest_sha256 == self.controller_visible_manifest_sha256:
            raise ValueError("raw and controller-visible manifests must be independently bound")
        if self.attestation_hash != _calculated_hash(self, "attestation_hash"):
            raise ValueError("arm runtime attestation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ArmRuntimeAttestation:
        return cls.model_validate(_addressed(values, "attestation_hash"))


class BudgetReservation(KernelContract):
    """Pre-operation reservation; failed started work remains chargeable."""

    schema_version: Literal["adaptive-loop-budget-reservation-v3"] = (
        "adaptive-loop-budget-reservation-v3"
    )
    receipt_kind: Literal["budget_reservation"] = "budget_reservation"
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    attestation_hash: Sha256
    reservation_id: StableId
    operation_kind: BudgetOperationKind
    reserved: BudgetVector
    made_before_operation: Literal[True] = True
    failed_attempts_are_chargeable: Literal[True] = True
    reservation_hash: Sha256

    @model_validator(mode="after")
    def _validate_reservation(self) -> BudgetReservation:
        _validate_runtime_identity(self, self.cell_binding)
        counts = {name: int(getattr(self.reserved, name)) for name in _COUNT_FIELDS}
        if self.reserved.wall_time_milliseconds <= 0:
            raise ValueError("every operation must reserve positive wall time")
        if self.operation_kind in _MODEL_OPERATION_FIELDS:
            expected_field = _MODEL_OPERATION_FIELDS[self.operation_kind]
            if any(count != (1 if name == expected_field else 0) for name, count in counts.items()):
                raise ValueError("model reservation must charge exactly its request lane")
        elif self.operation_kind is BudgetOperationKind.TOOL_CALL:
            if counts["tool_calls"] != 1 or any(counts[name] != 0 for name in _COUNT_FIELDS[:-1]):
                raise ValueError("tool reservation must charge one tool call")
        elif any(counts.values()):
            raise ValueError("mechanical transition cannot reserve model/tool calls")
        if self.reservation_hash != _calculated_hash(self, "reservation_hash"):
            raise ValueError("budget reservation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BudgetReservation:
        return cls.model_validate(_addressed(values, "reservation_hash"))


class BudgetLedgerEntry(KernelContract):
    """One exact settlement, including failed operation cost."""

    schema_version: Literal["adaptive-loop-budget-ledger-entry-v3"] = (
        "adaptive-loop-budget-ledger-entry-v3"
    )
    receipt_kind: Literal["budget_settlement"] = "budget_settlement"
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    attestation_hash: Sha256
    sequence: int = Field(ge=1)
    reservation_id: StableId
    reservation_hash: Sha256
    outcome: BudgetOutcome
    operation_started: bool
    charged: BudgetVector
    evidence_receipt_hash: Sha256
    failed_started_operation_counted: Literal[True] = True
    entry_hash: Sha256

    @model_validator(mode="after")
    def _validate_entry(self) -> BudgetLedgerEntry:
        _validate_runtime_identity(self, self.cell_binding)
        if self.outcome is BudgetOutcome.CANCELLED_BEFORE_START:
            if self.operation_started or _vector_nonzero(self.charged):
                raise ValueError("pre-start cancellation must have zero cost")
        elif not self.operation_started:
            raise ValueError("started success/failure cannot hide operation start")
        if self.entry_hash != _calculated_hash(self, "entry_hash"):
            raise ValueError("budget settlement hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BudgetLedgerEntry:
        return cls.model_validate(_addressed(values, "entry_hash"))


class BudgetLedger(KernelContract):
    """Complete one-to-one reservation/settlement ledger for a cell."""

    schema_version: Literal["adaptive-loop-budget-ledger-v3"] = "adaptive-loop-budget-ledger-v3"
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    attestation_hash: Sha256
    budget_limit: BudgetVector
    reservations: list[BudgetReservation]
    settlements: list[BudgetLedgerEntry]
    declared_charged_total: BudgetVector
    declared_failed_charged_total: BudgetVector
    every_reservation_settled_exactly_once: Literal[True] = True
    failed_started_operations_counted: Literal[True] = True
    ledger_hash: Sha256

    @model_validator(mode="after")
    def _validate_ledger(self) -> BudgetLedger:
        _validate_runtime_identity(self, self.cell_binding)
        if len({item.reservation_id for item in self.reservations}) != len(self.reservations):
            raise ValueError("budget reservation IDs must be unique")
        if [item.sequence for item in self.settlements] != list(
            range(1, len(self.settlements) + 1)
        ):
            raise ValueError("budget settlements must be consecutively ordered")
        reservation_by_id = {item.reservation_id: item for item in self.reservations}
        if Counter(item.reservation_id for item in self.settlements) != Counter(
            item.reservation_id for item in self.reservations
        ):
            raise ValueError("every reservation needs exactly one settlement")
        for item in [*self.reservations, *self.settlements]:
            _require_same_runtime_identity(item, self)
        for settlement in self.settlements:
            reservation = reservation_by_id[settlement.reservation_id]
            if settlement.reservation_hash != reservation.reservation_hash:
                raise ValueError("settlement does not bind its reservation")
            expected = (
                BudgetVector()
                if settlement.outcome is BudgetOutcome.CANCELLED_BEFORE_START
                else _charged_from_reservation(
                    reservation,
                    settlement.charged.wall_time_milliseconds,
                )
            )
            if settlement.charged != expected:
                raise ValueError("settlement hides or invents reserved-lane usage")
        actual_total = _sum_vectors(item.charged for item in self.settlements)
        failed_total = _sum_vectors(
            item.charged for item in self.settlements if item.outcome is BudgetOutcome.FAILED
        )
        if self.declared_charged_total != actual_total:
            raise ValueError("declared budget total hides or invents usage")
        if self.declared_failed_charged_total != failed_total:
            raise ValueError("declared failed cost hides or invents usage")
        if actual_total.exceeds(self.budget_limit):
            raise ValueError("cell budget exceeds the preregistered limit")
        if self.ledger_hash != _calculated_hash(self, "ledger_hash"):
            raise ValueError("budget ledger hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BudgetLedger:
        return cls.model_validate(_addressed(values, "ledger_hash"))


class ProviderPreCallAnchor(KernelContract):
    """A request/reservation commitment recorded before provider transport."""

    schema_version: Literal["adaptive-loop-provider-precall-anchor-v3"] = (
        "adaptive-loop-provider-precall-anchor-v3"
    )
    receipt_kind: Literal["provider_precall_anchor"] = "provider_precall_anchor"
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    attestation_hash: Sha256
    pre_call_id: StableId
    reservation_id: StableId
    reservation_hash: Sha256
    execution_mode: ProviderExecutionMode
    provider_name: Literal["qwen", "diagnostic_double"]
    model_name: StableId
    provider_request_id: StableId | None = None
    request_payload_sha256: Sha256
    recorded_before_transport: Literal[True] = True
    external_transport_not_yet_claimed: Literal[True] = True
    provider_model_and_request_id_are_unverified_metadata: Literal[True] = True
    pre_call_hash: Sha256

    @model_validator(mode="after")
    def _validate_anchor(self) -> ProviderPreCallAnchor:
        _validate_runtime_identity(self, self.cell_binding)
        if self.execution_mode is ProviderExecutionMode.LIVE_QWEN_PROVIDER:
            if self.provider_name != "qwen" or "qwen" not in self.model_name.casefold():
                raise ValueError("live track must be an explicitly named Qwen model")
            if self.provider_request_id is None:
                raise ValueError("live pre-call needs the provider request ID")
        else:
            if self.provider_name != "diagnostic_double":
                raise ValueError("diagnostic track cannot claim a live provider")
            if self.model_name != "diagnostic-double":
                raise ValueError("diagnostic track must use the fixed double name")
            if self.provider_request_id is not None:
                raise ValueError("diagnostic track has no external provider request ID")
        if self.pre_call_hash != _calculated_hash(self, "pre_call_hash"):
            raise ValueError("provider pre-call hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ProviderPreCallAnchor:
        return cls.model_validate(_addressed(values, "pre_call_hash"))


class ExternalTransportAnchor(KernelContract):
    """Process-local transport integrity receipt with no external trust claim.

    The historical class name is retained for runner compatibility.  Bytes,
    HTTP metadata, adapter names, and provider/model IDs are all supplied or
    observed by the same process that builds this contract.  Consequently they
    can detect later mutation but cannot prove a network boundary, provider
    identity, model identity, or formal execution.
    """

    schema_version: Literal["adaptive-loop-external-transport-anchor-v3"] = (
        "adaptive-loop-external-transport-anchor-v3"
    )
    receipt_kind: Literal["external_transport_anchor"] = "external_transport_anchor"
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    attestation_hash: Sha256
    reservation_id: StableId
    reservation_hash: Sha256
    pre_call_id: StableId
    pre_call_hash: Sha256
    execution_mode: Literal["live_qwen_provider"] = "live_qwen_provider"
    provider_name: Literal["qwen"] = "qwen"
    model_name: StableId
    provider_request_id: StableId
    provider_response_id: StableId | None = None
    adapter_id: StableId
    request_payload_sha256: Sha256
    transport_metadata_sha256: Sha256
    http_metadata_sha256: Sha256 | None = None
    raw_provider_response_body_sha256: Sha256 | None = None
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    process_local_only: Literal[True] = True
    independent_external_signature_verified: Literal[False] = False
    provider_model_and_ids_are_unverified_metadata: Literal[True] = True
    external_process_or_service_boundary_crossed: Literal[False] = False
    formal_eligible: Literal[False] = False
    transport_anchor_hash: Sha256

    @model_validator(mode="after")
    def _validate_transport(self) -> ExternalTransportAnchor:
        _validate_runtime_identity(self, self.cell_binding)
        if "qwen" not in self.model_name.casefold():
            raise ValueError("external anchor model is not explicitly Qwen")
        if (self.http_metadata_sha256 is None) != (self.http_status_code is None):
            raise ValueError("HTTP metadata and status must appear together")
        if self.provider_response_id is not None and self.raw_provider_response_body_sha256 is None:
            raise ValueError("provider response ID requires the raw response body hash")
        if self.transport_anchor_hash != _calculated_hash(self, "transport_anchor_hash"):
            raise ValueError("external transport anchor hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ExternalTransportAnchor:
        return cls.model_validate(_addressed(values, "transport_anchor_hash"))


class ProviderAttemptReceipt(KernelContract):
    """One live or diagnostic attempt, successful or failed, with exact hashes."""

    schema_version: Literal["adaptive-loop-provider-attempt-receipt-v3"] = (
        "adaptive-loop-provider-attempt-receipt-v3"
    )
    receipt_kind: Literal["provider_attempt"] = "provider_attempt"
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    attestation_hash: Sha256
    attempt_id: StableId
    reservation_id: StableId
    reservation_hash: Sha256
    pre_call_id: StableId
    pre_call_hash: Sha256
    execution_mode: ProviderExecutionMode
    provider_name: Literal["qwen", "diagnostic_double"]
    model_name: StableId
    status: ProviderAttemptStatus
    failure_phase: ProviderFailurePhase | None = None
    provider_request_id: StableId | None = None
    provider_response_id: StableId | None = None
    request_payload_sha256: Sha256
    transport_metadata_sha256: Sha256 | None = None
    http_metadata_sha256: Sha256 | None = None
    raw_provider_response_body_sha256: Sha256 | None = None
    raw_visible_output_sha256: Sha256 | None = None
    raw_reasoning_sha256: Sha256 | None = None
    usage_sha256: Sha256 | None = None
    error_sha256: Sha256 | None = None
    external_transport_anchor: ExternalTransportAnchor | None = None
    formal_eligible: Literal[False] = False
    provider_model_and_ids_are_unverified_metadata: Literal[True] = True
    independent_external_signature_verified: Literal[False] = False
    diagnostic_output_is_scientific_evidence: Literal[False] = False
    receipt_hash: Sha256

    @model_validator(mode="after")
    def _validate_attempt(self) -> ProviderAttemptReceipt:
        _validate_runtime_identity(self, self.cell_binding)
        if self.status is ProviderAttemptStatus.SUCCEEDED:
            if self.failure_phase is not None or self.error_sha256 is not None:
                raise ValueError("successful provider attempt cannot carry an error")
            if any(
                value is None
                for value in (
                    self.raw_visible_output_sha256,
                    self.raw_reasoning_sha256,
                    self.usage_sha256,
                )
            ):
                raise ValueError("successful attempt lacks output/reasoning/usage hashes")
        else:
            if self.failure_phase is None or self.error_sha256 is None:
                raise ValueError("failed attempt needs phase and error hash")

        if self.execution_mode is ProviderExecutionMode.DIAGNOSTIC_DOUBLE:
            if self.provider_name != "diagnostic_double" or self.model_name != "diagnostic-double":
                raise ValueError("diagnostic track cannot masquerade as Qwen")
            if any(
                value is not None
                for value in (
                    self.provider_request_id,
                    self.provider_response_id,
                    self.external_transport_anchor,
                    self.transport_metadata_sha256,
                    self.http_metadata_sha256,
                    self.raw_provider_response_body_sha256,
                )
            ):
                raise ValueError("diagnostic track cannot claim external transport")
        else:
            if self.provider_name != "qwen" or "qwen" not in self.model_name.casefold():
                raise ValueError("live provider receipt must explicitly identify Qwen")
            if self.provider_request_id is None:
                raise ValueError("live attempt needs the provider request ID")
            anchor = self.external_transport_anchor
            if anchor is None:
                if not (
                    self.status is ProviderAttemptStatus.FAILED
                    and self.failure_phase is ProviderFailurePhase.PREFLIGHT
                ):
                    raise ValueError("transported live attempt needs an external anchor")
                if any(
                    value is not None
                    for value in (
                        self.provider_response_id,
                        self.transport_metadata_sha256,
                        self.http_metadata_sha256,
                        self.raw_provider_response_body_sha256,
                    )
                ):
                    raise ValueError("preflight failure cannot claim transport evidence")
            else:
                _require_same_runtime_identity(anchor, self)
                if (
                    anchor.reservation_id,
                    anchor.reservation_hash,
                    anchor.pre_call_id,
                    anchor.pre_call_hash,
                    anchor.model_name,
                    anchor.provider_request_id,
                    anchor.provider_response_id,
                    anchor.request_payload_sha256,
                    anchor.transport_metadata_sha256,
                    anchor.http_metadata_sha256,
                    anchor.raw_provider_response_body_sha256,
                ) != (
                    self.reservation_id,
                    self.reservation_hash,
                    self.pre_call_id,
                    self.pre_call_hash,
                    self.model_name,
                    self.provider_request_id,
                    self.provider_response_id,
                    self.request_payload_sha256,
                    self.transport_metadata_sha256,
                    self.http_metadata_sha256,
                    self.raw_provider_response_body_sha256,
                ):
                    raise ValueError("provider attempt disagrees with transport anchor")
            if self.status is ProviderAttemptStatus.SUCCEEDED and (
                anchor is None
                or self.provider_response_id is None
                or self.http_metadata_sha256 is None
                or self.raw_provider_response_body_sha256 is None
            ):
                raise ValueError("successful live attempt lacks complete transport response")
        if self.receipt_hash != _calculated_hash(self, "receipt_hash"):
            raise ValueError("provider attempt receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ProviderAttemptReceipt:
        return cls.model_validate(_addressed(values, "receipt_hash"))


class MechanicalChallengeTransitionReceipt(KernelContract):
    """Deterministic 12-turn public stimulus injection, never model evidence."""

    schema_version: Literal["adaptive-loop-mechanical-transition-receipt-v3"] = (
        "adaptive-loop-mechanical-transition-receipt-v3"
    )
    receipt_kind: Literal["mechanical_challenge_transition"] = "mechanical_challenge_transition"
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    attestation_hash: Sha256
    transition_id: StableId
    reservation_id: StableId
    reservation_hash: Sha256
    transition_kind: Literal["inject_public_scenario_stimuli"] = "inject_public_scenario_stimuli"
    public_stimulus_hashes: list[Sha256] = Field(min_length=12, max_length=12)
    input_state_sha256: Sha256
    challenge_fixture_sha256: Sha256
    output_state_sha256: Sha256
    terminal_turn_index: Literal[12] = 12
    every_public_stimulus_injected_exactly_once: Literal[True] = True
    terminal_turn_reached: Literal[True] = True
    model_request_count: Literal[0] = 0
    network_request_count: Literal[0] = 0
    formal_provider_eligible: Literal[False] = False
    scientific_evidence_established: Literal[False] = False
    receipt_hash: Sha256

    @model_validator(mode="after")
    def _validate_transition(self) -> MechanicalChallengeTransitionReceipt:
        _validate_runtime_identity(self, self.cell_binding)
        if len(set(self.public_stimulus_hashes)) != 12:
            raise ValueError("all 12 public stimulus commitments must be distinct")
        if self.receipt_hash != _calculated_hash(self, "receipt_hash"):
            raise ValueError("mechanical transition receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanicalChallengeTransitionReceipt:
        return cls.model_validate(_addressed(values, "receipt_hash"))


class CellRuntimeEvidenceBundle(KernelContract):
    """Write-once replay payload for all non-journal cell evidence."""

    schema_version: Literal["adaptive-loop-cell-runtime-evidence-bundle-v3"] = (
        "adaptive-loop-cell-runtime-evidence-bundle-v3"
    )
    receipt_bridge_hash: Sha256
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    arm_attestation: ArmRuntimeAttestation
    budget_ledger: BudgetLedger
    provider_pre_calls: list[ProviderPreCallAnchor]
    transport_anchors: list[ExternalTransportAnchor]
    provider_attempts: list[ProviderAttemptReceipt]
    mechanical_transitions: list[MechanicalChallengeTransitionReceipt]
    hidden_scoring_values_absent: Literal[True] = True
    scoring_not_executed: Literal[True] = True
    scientific_result_generated: Literal[False] = False
    runtime_evidence_hash: Sha256

    @model_validator(mode="after")
    def _validate_bundle(self) -> CellRuntimeEvidenceBundle:
        if self.arm_attestation.cell_binding != self.cell_binding:
            raise ValueError("runtime bundle attestation uses another cell")
        for item in (
            self.budget_ledger,
            *self.provider_pre_calls,
            *self.transport_anchors,
            *self.provider_attempts,
            *self.mechanical_transitions,
        ):
            _require_same_runtime_identity(item, self.arm_attestation)
        _require_unique_hashes(
            [item.pre_call_hash for item in self.provider_pre_calls],
            "provider pre-call",
        )
        _require_unique_hashes(
            [item.transport_anchor_hash for item in self.transport_anchors],
            "transport anchor",
        )
        _require_unique_hashes(
            [item.receipt_hash for item in self.provider_attempts],
            "provider attempt",
        )
        _require_unique_hashes(
            [item.receipt_hash for item in self.mechanical_transitions],
            "mechanical transition",
        )
        if self.runtime_evidence_hash != _calculated_hash(self, "runtime_evidence_hash"):
            raise ValueError("runtime evidence bundle hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CellRuntimeEvidenceBundle:
        return cls.model_validate(_addressed(values, "runtime_evidence_hash"))


class CellJournalEntry(KernelContract):
    """One append-only forward-hashed cell journal entry."""

    schema_version: Literal["adaptive-loop-cell-journal-entry-v3"] = (
        "adaptive-loop-cell-journal-entry-v3"
    )
    receipt_kind: Literal["cell_journal_entry"] = "cell_journal_entry"
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    trajectory_id: StableId
    attestation_hash: Sha256
    sequence: int = Field(ge=1)
    event_kind: CellJournalEventKind
    payload_hash: Sha256
    previous_entry_hash: Sha256 | None = None
    entry_hash: Sha256

    @model_validator(mode="after")
    def _validate_entry(self) -> CellJournalEntry:
        _validate_runtime_identity(self, self.cell_binding)
        if self.sequence == 1 and self.previous_entry_hash is not None:
            raise ValueError("first journal entry cannot have a predecessor")
        if self.sequence > 1 and self.previous_entry_hash is None:
            raise ValueError("later journal entry must bind its predecessor")
        if self.entry_hash != _calculated_hash(self, "entry_hash"):
            raise ValueError("journal entry hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CellJournalEntry:
        return cls.model_validate(_addressed(values, "entry_hash"))


class CellJournalReplay(KernelContract):
    """Deterministic replay digest proving complete ordered coverage."""

    schema_version: Literal["adaptive-loop-cell-journal-replay-v3"] = (
        "adaptive-loop-cell-journal-replay-v3"
    )
    receipt_bridge_hash: Sha256
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    attestation_hash: Sha256
    entry_count: int = Field(ge=1)
    journal_head_hash: Sha256
    ordered_entry_hashes: list[Sha256]
    reservation_hashes: list[Sha256]
    settlement_hashes: list[Sha256]
    pre_call_hashes: list[Sha256]
    transport_anchor_hashes: list[Sha256]
    provider_attempt_hashes: list[Sha256]
    mechanical_transition_hashes: list[Sha256]
    runtime_evidence_hash: Sha256
    complete_budget_replay: Literal[True] = True
    complete_transport_replay: Literal[True] = True
    complete_arm_replay: Literal[True] = True
    complete_mechanical_replay: Literal[True] = True
    hidden_scoring_values_absent: Literal[True] = True
    replay_hash: Sha256

    @model_validator(mode="after")
    def _validate_replay_hash(self) -> CellJournalReplay:
        if self.entry_count != len(self.ordered_entry_hashes):
            raise ValueError("journal replay entry count mismatch")
        if not self.ordered_entry_hashes or self.journal_head_hash != self.ordered_entry_hashes[-1]:
            raise ValueError("journal replay head mismatch")
        if self.replay_hash != _calculated_hash(self, "replay_hash"):
            raise ValueError("journal replay hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CellJournalReplay:
        return cls.model_validate(_addressed(values, "replay_hash"))


class TerminalEnvelope(KernelContract):
    """Write-once terminal commitment; deliberately contains no score/result."""

    schema_version: Literal["adaptive-loop-terminal-envelope-v3"] = (
        "adaptive-loop-terminal-envelope-v3"
    )
    receipt_kind: Literal["terminal_envelope"] = "terminal_envelope"
    receipt_bridge_hash: Sha256
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    attestation_hash: Sha256
    runtime_evidence_hash: Sha256
    journal_replay_hash: Sha256
    journal_entry_count: int = Field(ge=1)
    journal_head_hash: Sha256
    budget_ledger_hash: Sha256
    reservation_hashes: list[Sha256]
    settlement_hashes: list[Sha256]
    pre_call_hashes: list[Sha256]
    transport_anchor_hashes: list[Sha256]
    provider_attempt_hashes: list[Sha256]
    mechanical_transition_hashes: list[Sha256]
    audit_raw_manifest_sha256: Sha256
    controller_visible_manifest_sha256: Sha256
    runtime_failure_recorded: bool
    formal_eligible: Literal[False] = False
    process_local_transport_integrity_only: Literal[True] = True
    independently_signed_transport_gateway_verified: Literal[False] = False
    write_once_sealed: Literal[True] = True
    hidden_scoring_values_absent: Literal[True] = True
    scoring_not_executed: Literal[True] = True
    scientific_result_generated: Literal[False] = False
    terminal_hash: Sha256

    @model_validator(mode="after")
    def _validate_terminal(self) -> TerminalEnvelope:
        if self.terminal_hash != _calculated_hash(self, "terminal_hash"):
            raise ValueError("terminal envelope hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TerminalEnvelope:
        return cls.model_validate(_addressed(values, "terminal_hash"))


class CellTerminalCommitment(KernelContract):
    schema_version: Literal["adaptive-loop-cell-terminal-commitment-v3"] = (
        "adaptive-loop-cell-terminal-commitment-v3"
    )
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    terminal_hash: Sha256
    runtime_evidence_hash: Sha256
    journal_replay_hash: Sha256
    formal_eligible: Literal[False] = False
    runtime_failure_recorded: bool
    commitment_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> CellTerminalCommitment:
        if self.commitment_hash != _calculated_hash(self, "commitment_hash"):
            raise ValueError("cell terminal commitment hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CellTerminalCommitment:
        return cls.model_validate(_addressed(values, "commitment_hash"))


class AdaptiveLoopBenchmarkTerminalSetSeal(KernelContract):
    """Global barrier proof for the complete official 240-cell set."""

    schema_version: Literal["adaptive-loop-terminal-set-seal-v3"] = (
        "adaptive-loop-terminal-set-seal-v3"
    )
    receipt_bridge_hash: Sha256
    parent_v1_protocol_hash: Sha256
    execution_protocol_hash: Sha256
    public_scenario_panel_hash: Sha256
    blinded_manifest_hash: Sha256
    runner_assignment_manifest_hash: Sha256
    private_scoring_manifest_hash: Sha256
    commitments: list[CellTerminalCommitment] = Field(min_length=240, max_length=240)
    terminal_envelope_count: Literal[240] = 240
    all_terminal_envelopes_write_once: Literal[True] = True
    all_budget_transport_arm_mechanical_evidence_replayed: Literal[True] = True
    reveal_barrier_closed_before_this_seal: Literal[True] = True
    scoring_not_executed: Literal[True] = True
    scientific_result_generated: Literal[False] = False
    terminal_set_hash: Sha256

    @model_validator(mode="after")
    def _validate_set(self) -> AdaptiveLoopBenchmarkTerminalSetSeal:
        if len({item.cell_binding.blinded_cell_id for item in self.commitments}) != 240:
            raise ValueError("terminal set does not contain 240 distinct cells")
        if len({item.commitment_hash for item in self.commitments}) != 240:
            raise ValueError("terminal commitment hashes must be unique")
        if self.terminal_set_hash != _calculated_hash(self, "terminal_set_hash"):
            raise ValueError("terminal set seal hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkTerminalSetSeal:
        return cls.model_validate(_addressed(values, "terminal_set_hash"))


class AdaptiveLoopBenchmarkRevealAuthorization(KernelContract):
    """Authorization to reveal scoring inputs after complete runtime replay."""

    schema_version: Literal["adaptive-loop-reveal-authorization-v3"] = (
        "adaptive-loop-reveal-authorization-v3"
    )
    receipt_bridge_hash: Sha256
    terminal_set_hash: Sha256
    execution_protocol_hash: Sha256
    private_scoring_manifest_hash: Sha256
    terminal_envelope_count: Literal[240] = 240
    complete_runtime_replay_verified: Literal[True] = True
    reveal_barrier_opened_after_global_seal: Literal[True] = True
    runner_only_scoring_manifest_loaded_after_seal: Literal[True] = True
    scoring_not_executed: Literal[True] = True
    scientific_result_generated: Literal[False] = False
    authorization_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkRevealAuthorization:
        if self.authorization_hash != _calculated_hash(self, "authorization_hash"):
            raise ValueError("reveal authorization hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkRevealAuthorization:
        return cls.model_validate(_addressed(values, "authorization_hash"))


class AdaptiveLoopBenchmarkEvaluatorCellScoreInput(KernelContract):
    """Post-seal input only; no scientific outcome is computed here."""

    schema_version: Literal["adaptive-loop-evaluator-cell-score-input-v3"] = (
        "adaptive-loop-evaluator-cell-score-input-v3"
    )
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    terminal_hash: Sha256
    runtime_formal_eligible: Literal[False] = False
    runtime_failure_recorded: bool
    machine_oracle: AdaptiveLoopBenchmarkMachineOracle
    scoring_not_executed: Literal[True] = True
    scientific_result_generated: Literal[False] = False

    @model_validator(mode="after")
    def _validate_oracle_binding(self) -> AdaptiveLoopBenchmarkEvaluatorCellScoreInput:
        if (
            self.machine_oracle.scenario_id,
            self.machine_oracle.public_scenario_hash,
        ) != (
            self.cell_binding.scenario_id,
            self.cell_binding.public_scenario_hash,
        ):
            raise ValueError("post-seal oracle does not match the cell scenario")
        return self


class AdaptiveLoopBenchmarkEvaluatorScoreInputManifest(KernelContract):
    """Post-seal 240-cell evaluator input, still without scores or results."""

    schema_version: Literal["adaptive-loop-evaluator-score-input-manifest-v3"] = (
        "adaptive-loop-evaluator-score-input-manifest-v3"
    )
    authorization_hash: Sha256
    terminal_set_hash: Sha256
    private_scoring_manifest_hash: Sha256
    cells: list[AdaptiveLoopBenchmarkEvaluatorCellScoreInput] = Field(
        min_length=240,
        max_length=240,
    )
    cell_count: Literal[240] = 240
    evaluator_only_post_seal: Literal[True] = True
    scoring_not_executed: Literal[True] = True
    score_fields_absent: Literal[True] = True
    scientific_result_generated: Literal[False] = False
    score_input_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> AdaptiveLoopBenchmarkEvaluatorScoreInputManifest:
        if len({item.cell_binding.blinded_cell_id for item in self.cells}) != 240:
            raise ValueError("score input must contain 240 distinct cells")
        if self.score_input_hash != _calculated_hash(self, "score_input_hash"):
            raise ValueError("evaluator score input hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkEvaluatorScoreInputManifest:
        return cls.model_validate(_addressed(values, "score_input_hash"))


class AdaptiveLoopBenchmarkBlindRevealPackage(KernelContract):
    authorization: AdaptiveLoopBenchmarkRevealAuthorization
    score_input: AdaptiveLoopBenchmarkEvaluatorScoreInputManifest

    @model_validator(mode="after")
    def _validate_package(self) -> AdaptiveLoopBenchmarkBlindRevealPackage:
        if self.score_input.authorization_hash != self.authorization.authorization_hash:
            raise ValueError("score input does not bind reveal authorization")
        if self.score_input.terminal_set_hash != self.authorization.terminal_set_hash:
            raise ValueError("score input does not bind terminal set")
        return self


def build_adaptive_loop_benchmark_receipt_bridge(
    bundle: AdaptiveLoopBenchmarkExecutionBundle,
) -> AdaptiveLoopBenchmarkReceiptBridge:
    """Build the exact runner-only v3 bridge without copying private oracles."""

    protocol = bundle.protocol
    blinded = bundle.blinded_cells
    runner = bundle.runner_assignments
    # Bundle validation is repeated here so callers cannot pass an unvalidated proxy.
    AdaptiveLoopBenchmarkExecutionBundle.model_validate(bundle.model_dump(mode="json"))
    assignments = {item.blinded_cell_id: item for item in runner.assignments}
    cells: list[AdaptiveLoopBenchmarkCellExecutionBinding] = []
    for item in blinded.cells:
        assignment = assignments[item.blinded_cell_id]
        cells.append(
            AdaptiveLoopBenchmarkCellExecutionBinding.create(
                schema_version="adaptive-loop-cell-execution-binding-v3",
                parent_v1_protocol_hash=protocol.parent_v1_protocol_hash,
                execution_protocol_hash=protocol.execution_protocol_hash,
                public_scenario_panel_hash=protocol.public_scenario_panel_hash,
                blinded_manifest_hash=blinded.blinded_manifest_hash,
                runner_assignment_manifest_hash=runner.runner_assignment_manifest_hash,
                private_scoring_manifest_hash=protocol.private_scoring_manifest_hash,
                blinded_cell_id=item.blinded_cell_id,
                scenario_id=item.scenario_id,
                challenge_kind=item.challenge_kind,
                public_scenario_hash=item.public_scenario_hash,
                run_position=item.run_position,
                model_draw_ordinal=item.model_draw_ordinal,
                sequence_id=assignment.sequence_id,
                arm=assignment.arm,
                runner_only_assignment=True,
                hidden_scoring_values_absent=True,
            )
        )
    return AdaptiveLoopBenchmarkReceiptBridge.create(
        schema_version="adaptive-loop-benchmark-receipt-bridge-v3",
        parent_v1_protocol_hash=protocol.parent_v1_protocol_hash,
        execution_protocol_hash=protocol.execution_protocol_hash,
        public_scenario_panel_hash=protocol.public_scenario_panel_hash,
        blinded_manifest_hash=blinded.blinded_manifest_hash,
        runner_assignment_manifest_hash=runner.runner_assignment_manifest_hash,
        private_scoring_manifest_hash=protocol.private_scoring_manifest_hash,
        execution_protocol=protocol,
        blinded_manifest=blinded,
        runner_assignment_manifest=runner,
        cells=cells,
        runner_only=True,
        controller_access_allowed=False,
        blinded_evaluator_access_before_reveal_allowed=False,
        hidden_scoring_values_absent=True,
        v1_seed_repeat_identity_formally_eligible=False,
    )


def build_arm_runtime_attestation(
    *,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    blinded_cell_id: str,
    audit_raw_memory_plane_id: str,
    controller_visible_memory_plane_id: str,
    audit_raw_manifest: bytes,
    controller_visible_manifest: bytes,
) -> ArmRuntimeAttestation:
    binding = bridge.cell(blinded_cell_id)
    return ArmRuntimeAttestation.create(
        schema_version="adaptive-loop-arm-runtime-attestation-v3",
        receipt_kind="arm_runtime_attestation",
        receipt_bridge_hash=bridge.receipt_bridge_hash,
        cell_binding=binding,
        trajectory_id=_trajectory_id(binding),
        capability_profile=_frozen_arm_profile(binding.arm),
        audit_raw_memory_plane_id=audit_raw_memory_plane_id,
        controller_visible_memory_plane_id=controller_visible_memory_plane_id,
        audit_raw_manifest_sha256=_sha256_bytes(audit_raw_manifest),
        controller_visible_manifest_sha256=_sha256_bytes(controller_visible_manifest),
        audit_raw_plane_excluded_from_controller_context=True,
        controller_visible_plane_cannot_mutate_audit_raw=True,
        arm_switch_after_trajectory_start_allowed=False,
    )


def build_budget_reservation(
    *,
    attestation: ArmRuntimeAttestation,
    reservation_id: str,
    operation_kind: BudgetOperationKind,
    maximum_wall_time_milliseconds: int,
) -> BudgetReservation:
    reserved = BudgetVector(wall_time_milliseconds=maximum_wall_time_milliseconds)
    values = reserved.model_dump(mode="json")
    if operation_kind in _MODEL_OPERATION_FIELDS:
        values[_MODEL_OPERATION_FIELDS[operation_kind]] = 1
    elif operation_kind is BudgetOperationKind.TOOL_CALL:
        values["tool_calls"] = 1
    return BudgetReservation.create(
        schema_version="adaptive-loop-budget-reservation-v3",
        receipt_kind="budget_reservation",
        cell_binding=attestation.cell_binding,
        trajectory_id=attestation.trajectory_id,
        attestation_hash=attestation.attestation_hash,
        reservation_id=reservation_id,
        operation_kind=operation_kind,
        reserved=BudgetVector.model_validate(values),
        made_before_operation=True,
        failed_attempts_are_chargeable=True,
    )


def build_budget_ledger_entry(
    *,
    reservation: BudgetReservation,
    sequence: int,
    outcome: BudgetOutcome,
    actual_wall_time_milliseconds: int,
    evidence_receipt_hash: str,
) -> BudgetLedgerEntry:
    operation_started = outcome is not BudgetOutcome.CANCELLED_BEFORE_START
    charged = (
        _charged_from_reservation(reservation, actual_wall_time_milliseconds)
        if operation_started
        else BudgetVector()
    )
    return BudgetLedgerEntry.create(
        schema_version="adaptive-loop-budget-ledger-entry-v3",
        receipt_kind="budget_settlement",
        cell_binding=reservation.cell_binding,
        trajectory_id=reservation.trajectory_id,
        attestation_hash=reservation.attestation_hash,
        sequence=sequence,
        reservation_id=reservation.reservation_id,
        reservation_hash=reservation.reservation_hash,
        outcome=outcome,
        operation_started=operation_started,
        charged=charged,
        evidence_receipt_hash=evidence_receipt_hash,
        failed_started_operation_counted=True,
    )


def build_budget_ledger(
    *,
    attestation: ArmRuntimeAttestation,
    budget_limit: BudgetVector,
    reservations: Sequence[BudgetReservation],
    settlements: Sequence[BudgetLedgerEntry],
) -> BudgetLedger:
    return BudgetLedger.create(
        schema_version="adaptive-loop-budget-ledger-v3",
        cell_binding=attestation.cell_binding,
        trajectory_id=attestation.trajectory_id,
        attestation_hash=attestation.attestation_hash,
        budget_limit=budget_limit,
        reservations=list(reservations),
        settlements=list(settlements),
        declared_charged_total=_sum_vectors(item.charged for item in settlements),
        declared_failed_charged_total=_sum_vectors(
            item.charged for item in settlements if item.outcome is BudgetOutcome.FAILED
        ),
        every_reservation_settled_exactly_once=True,
        failed_started_operations_counted=True,
    )


def build_provider_pre_call_anchor(
    *,
    attestation: ArmRuntimeAttestation,
    reservation: BudgetReservation,
    pre_call_id: str,
    execution_mode: ProviderExecutionMode,
    model_name: str,
    request_payload: bytes,
    provider_request_id: str | None = None,
) -> ProviderPreCallAnchor:
    _require_same_runtime_identity(reservation, attestation)
    if reservation.operation_kind not in _MODEL_OPERATION_FIELDS:
        raise AdaptiveLoopBenchmarkReceiptError(
            "provider pre-call requires a model-request reservation"
        )
    provider_name = (
        "qwen"
        if execution_mode is ProviderExecutionMode.LIVE_QWEN_PROVIDER
        else "diagnostic_double"
    )
    return ProviderPreCallAnchor.create(
        schema_version="adaptive-loop-provider-precall-anchor-v3",
        receipt_kind="provider_precall_anchor",
        cell_binding=attestation.cell_binding,
        trajectory_id=attestation.trajectory_id,
        attestation_hash=attestation.attestation_hash,
        pre_call_id=pre_call_id,
        reservation_id=reservation.reservation_id,
        reservation_hash=reservation.reservation_hash,
        execution_mode=execution_mode,
        provider_name=provider_name,
        model_name=model_name,
        provider_request_id=provider_request_id,
        request_payload_sha256=_sha256_bytes(request_payload),
        recorded_before_transport=True,
        external_transport_not_yet_claimed=True,
        provider_model_and_request_id_are_unverified_metadata=True,
    )


def build_external_transport_anchor(
    *,
    attestation: ArmRuntimeAttestation,
    reservation: BudgetReservation,
    pre_call: ProviderPreCallAnchor,
    adapter_id: str,
    request_payload: bytes,
    transport_metadata: bytes,
    http_metadata: bytes | None,
    raw_response_body: bytes | None,
    http_status_code: int | None,
    provider_response_id: str | None,
) -> ExternalTransportAnchor:
    for item in (reservation, pre_call):
        _require_same_runtime_identity(item, attestation)
    if pre_call.execution_mode is not ProviderExecutionMode.LIVE_QWEN_PROVIDER:
        raise AdaptiveLoopBenchmarkReceiptError(
            "diagnostic pre-call cannot acquire an external transport anchor"
        )
    if (
        pre_call.reservation_id,
        pre_call.reservation_hash,
        pre_call.request_payload_sha256,
    ) != (
        reservation.reservation_id,
        reservation.reservation_hash,
        _sha256_bytes(request_payload),
    ):
        raise AdaptiveLoopBenchmarkReceiptError(
            "external transport does not match its pre-call reservation/request"
        )
    return ExternalTransportAnchor.create(
        schema_version="adaptive-loop-external-transport-anchor-v3",
        receipt_kind="external_transport_anchor",
        cell_binding=attestation.cell_binding,
        trajectory_id=attestation.trajectory_id,
        attestation_hash=attestation.attestation_hash,
        reservation_id=reservation.reservation_id,
        reservation_hash=reservation.reservation_hash,
        pre_call_id=pre_call.pre_call_id,
        pre_call_hash=pre_call.pre_call_hash,
        execution_mode="live_qwen_provider",
        provider_name="qwen",
        model_name=pre_call.model_name,
        provider_request_id=pre_call.provider_request_id,
        provider_response_id=provider_response_id,
        adapter_id=adapter_id,
        request_payload_sha256=pre_call.request_payload_sha256,
        transport_metadata_sha256=_sha256_bytes(transport_metadata),
        http_metadata_sha256=_optional_sha256(http_metadata),
        raw_provider_response_body_sha256=_optional_sha256(raw_response_body),
        http_status_code=http_status_code,
        process_local_only=True,
        independent_external_signature_verified=False,
        provider_model_and_ids_are_unverified_metadata=True,
        external_process_or_service_boundary_crossed=False,
        formal_eligible=False,
    )


def build_provider_attempt_receipt(
    *,
    attestation: ArmRuntimeAttestation,
    attempt_id: str,
    request_reservation: BudgetReservation,
    pre_call: ProviderPreCallAnchor,
    status: ProviderAttemptStatus,
    request_payload: bytes,
    raw_visible_output: bytes | None,
    raw_reasoning: bytes | None,
    usage: bytes | None,
    error: bytes | None,
    failure_phase: ProviderFailurePhase | None = None,
    external_transport_anchor: ExternalTransportAnchor | None = None,
) -> ProviderAttemptReceipt:
    for item in (request_reservation, pre_call):
        _require_same_runtime_identity(item, attestation)
    if (
        pre_call.reservation_id,
        pre_call.reservation_hash,
        pre_call.request_payload_sha256,
    ) != (
        request_reservation.reservation_id,
        request_reservation.reservation_hash,
        _sha256_bytes(request_payload),
    ):
        raise AdaptiveLoopBenchmarkReceiptError(
            "provider attempt does not match its pre-call request"
        )
    anchor = external_transport_anchor
    return ProviderAttemptReceipt.create(
        schema_version="adaptive-loop-provider-attempt-receipt-v3",
        receipt_kind="provider_attempt",
        cell_binding=attestation.cell_binding,
        trajectory_id=attestation.trajectory_id,
        attestation_hash=attestation.attestation_hash,
        attempt_id=attempt_id,
        reservation_id=request_reservation.reservation_id,
        reservation_hash=request_reservation.reservation_hash,
        pre_call_id=pre_call.pre_call_id,
        pre_call_hash=pre_call.pre_call_hash,
        execution_mode=pre_call.execution_mode,
        provider_name=pre_call.provider_name,
        model_name=pre_call.model_name,
        status=status,
        failure_phase=failure_phase,
        provider_request_id=pre_call.provider_request_id,
        provider_response_id=(anchor.provider_response_id if anchor else None),
        request_payload_sha256=pre_call.request_payload_sha256,
        transport_metadata_sha256=(anchor.transport_metadata_sha256 if anchor else None),
        http_metadata_sha256=(anchor.http_metadata_sha256 if anchor else None),
        raw_provider_response_body_sha256=(
            anchor.raw_provider_response_body_sha256 if anchor else None
        ),
        raw_visible_output_sha256=_optional_sha256(raw_visible_output),
        raw_reasoning_sha256=_optional_sha256(raw_reasoning),
        usage_sha256=_optional_sha256(usage),
        error_sha256=_optional_sha256(error),
        external_transport_anchor=anchor,
        formal_eligible=False,
        provider_model_and_ids_are_unverified_metadata=True,
        independent_external_signature_verified=False,
        diagnostic_output_is_scientific_evidence=False,
    )


def build_mechanical_transition_receipt(
    *,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    attestation: ArmRuntimeAttestation,
    walltime_reservation: BudgetReservation,
    transition_id: str,
    input_state: bytes,
    challenge_fixture: bytes,
    output_state: bytes,
) -> MechanicalChallengeTransitionReceipt:
    _require_binding_in_bridge(bridge, attestation.cell_binding)
    _require_same_runtime_identity(walltime_reservation, attestation)
    if walltime_reservation.operation_kind is not BudgetOperationKind.MECHANICAL_TRANSITION:
        raise AdaptiveLoopBenchmarkReceiptError(
            "mechanical receipt needs a mechanical-transition reservation"
        )
    scenario = _scenario_for_binding(bridge, attestation.cell_binding)
    return MechanicalChallengeTransitionReceipt.create(
        schema_version="adaptive-loop-mechanical-transition-receipt-v3",
        receipt_kind="mechanical_challenge_transition",
        cell_binding=attestation.cell_binding,
        trajectory_id=attestation.trajectory_id,
        attestation_hash=attestation.attestation_hash,
        transition_id=transition_id,
        reservation_id=walltime_reservation.reservation_id,
        reservation_hash=walltime_reservation.reservation_hash,
        transition_kind="inject_public_scenario_stimuli",
        public_stimulus_hashes=[item.stimulus_hash for item in scenario.stimuli],
        input_state_sha256=_sha256_bytes(input_state),
        challenge_fixture_sha256=_sha256_bytes(challenge_fixture),
        output_state_sha256=_sha256_bytes(output_state),
        terminal_turn_index=12,
        every_public_stimulus_injected_exactly_once=True,
        terminal_turn_reached=True,
        model_request_count=0,
        network_request_count=0,
        formal_provider_eligible=False,
        scientific_evidence_established=False,
    )


def build_cell_runtime_evidence_bundle(
    *,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    attestation: ArmRuntimeAttestation,
    budget_ledger: BudgetLedger,
    provider_pre_calls: Sequence[ProviderPreCallAnchor],
    transport_anchors: Sequence[ExternalTransportAnchor],
    provider_attempts: Sequence[ProviderAttemptReceipt],
    mechanical_transitions: Sequence[MechanicalChallengeTransitionReceipt],
) -> CellRuntimeEvidenceBundle:
    _require_binding_in_bridge(bridge, attestation.cell_binding)
    evidence = CellRuntimeEvidenceBundle.create(
        schema_version="adaptive-loop-cell-runtime-evidence-bundle-v3",
        receipt_bridge_hash=bridge.receipt_bridge_hash,
        cell_binding=attestation.cell_binding,
        arm_attestation=attestation,
        budget_ledger=budget_ledger,
        provider_pre_calls=list(provider_pre_calls),
        transport_anchors=list(transport_anchors),
        provider_attempts=list(provider_attempts),
        mechanical_transitions=list(mechanical_transitions),
        hidden_scoring_values_absent=True,
        scoring_not_executed=True,
        scientific_result_generated=False,
    )
    _validate_cell_artifacts(bridge, evidence)
    return evidence


def build_cell_journal_entry(
    *,
    attestation: ArmRuntimeAttestation,
    event_kind: CellJournalEventKind,
    payload_hash: str,
    previous_entry: CellJournalEntry | None,
) -> CellJournalEntry:
    if previous_entry is not None:
        _require_same_runtime_identity(previous_entry, attestation)
    return CellJournalEntry.create(
        schema_version="adaptive-loop-cell-journal-entry-v3",
        receipt_kind="cell_journal_entry",
        cell_binding=attestation.cell_binding,
        trajectory_id=attestation.trajectory_id,
        attestation_hash=attestation.attestation_hash,
        sequence=1 if previous_entry is None else previous_entry.sequence + 1,
        event_kind=event_kind,
        payload_hash=payload_hash,
        previous_entry_hash=(previous_entry.entry_hash if previous_entry else None),
    )


def replay_cell_journal(
    *,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    entries: Sequence[CellJournalEntry],
    runtime_evidence: CellRuntimeEvidenceBundle,
) -> CellJournalReplay:
    _validate_cell_artifacts(bridge, runtime_evidence)
    _verify_journal_chain(entries)
    attestation = runtime_evidence.arm_attestation
    for entry in entries:
        _require_same_runtime_identity(entry, attestation)

    expected: list[tuple[CellJournalEventKind, str]] = [
        (CellJournalEventKind.ARM_ATTESTED, attestation.attestation_hash),
    ]
    expected.extend(
        (CellJournalEventKind.BUDGET_RESERVED, item.reservation_hash)
        for item in runtime_evidence.budget_ledger.reservations
    )
    expected.extend(
        (CellJournalEventKind.PROVIDER_PRECALL_RECORDED, item.pre_call_hash)
        for item in runtime_evidence.provider_pre_calls
    )
    expected.extend(
        (CellJournalEventKind.TRANSPORT_ANCHOR_RECORDED, item.transport_anchor_hash)
        for item in runtime_evidence.transport_anchors
    )
    expected.extend(
        (CellJournalEventKind.PROVIDER_ATTEMPT_RECORDED, item.receipt_hash)
        for item in runtime_evidence.provider_attempts
    )
    expected.extend(
        (CellJournalEventKind.MECHANICAL_TRANSITION_RECORDED, item.receipt_hash)
        for item in runtime_evidence.mechanical_transitions
    )
    expected.extend(
        (CellJournalEventKind.BUDGET_SETTLED, item.entry_hash)
        for item in runtime_evidence.budget_ledger.settlements
    )
    actual = [(item.event_kind, item.payload_hash) for item in entries]
    if Counter(actual) != Counter(expected):
        raise AdaptiveLoopBenchmarkReceiptError(
            "journal coverage differs from exact runtime evidence"
        )
    positions = {pair: index for index, pair in enumerate(actual)}
    if positions[(CellJournalEventKind.ARM_ATTESTED, attestation.attestation_hash)] != 0:
        raise AdaptiveLoopBenchmarkReceiptError("arm attestation must be the first event")
    settlements = {item.reservation_id: item for item in runtime_evidence.budget_ledger.settlements}
    pre_calls = {item.reservation_id: item for item in runtime_evidence.provider_pre_calls}
    attempts = {item.reservation_id: item for item in runtime_evidence.provider_attempts}
    mechanical = {item.reservation_id: item for item in runtime_evidence.mechanical_transitions}
    anchors = {item.reservation_id: item for item in runtime_evidence.transport_anchors}
    for reservation in runtime_evidence.budget_ledger.reservations:
        settlement = settlements[reservation.reservation_id]
        order = [positions[(CellJournalEventKind.BUDGET_RESERVED, reservation.reservation_hash)]]
        if reservation.reservation_id in attempts:
            pre_call = pre_calls[reservation.reservation_id]
            order.append(
                positions[(CellJournalEventKind.PROVIDER_PRECALL_RECORDED, pre_call.pre_call_hash)]
            )
            anchor = anchors.get(reservation.reservation_id)
            if anchor is not None:
                order.append(
                    positions[
                        (
                            CellJournalEventKind.TRANSPORT_ANCHOR_RECORDED,
                            anchor.transport_anchor_hash,
                        )
                    ]
                )
            attempt = attempts[reservation.reservation_id]
            order.append(
                positions[(CellJournalEventKind.PROVIDER_ATTEMPT_RECORDED, attempt.receipt_hash)]
            )
        elif reservation.reservation_id in mechanical:
            receipt = mechanical[reservation.reservation_id]
            order.append(
                positions[
                    (
                        CellJournalEventKind.MECHANICAL_TRANSITION_RECORDED,
                        receipt.receipt_hash,
                    )
                ]
            )
        else:
            raise AdaptiveLoopBenchmarkReceiptError(
                "reservation has no provider or mechanical evidence"
            )
        order.append(positions[(CellJournalEventKind.BUDGET_SETTLED, settlement.entry_hash)])
        if order != sorted(order) or len(order) != len(set(order)):
            raise AdaptiveLoopBenchmarkReceiptError(
                "journal operation order violates reserve/pre-call/transport/evidence/settle"
            )
    return CellJournalReplay.create(
        schema_version="adaptive-loop-cell-journal-replay-v3",
        receipt_bridge_hash=bridge.receipt_bridge_hash,
        cell_binding=attestation.cell_binding,
        attestation_hash=attestation.attestation_hash,
        entry_count=len(entries),
        journal_head_hash=entries[-1].entry_hash,
        ordered_entry_hashes=[item.entry_hash for item in entries],
        reservation_hashes=[
            item.reservation_hash for item in runtime_evidence.budget_ledger.reservations
        ],
        settlement_hashes=[item.entry_hash for item in runtime_evidence.budget_ledger.settlements],
        pre_call_hashes=[item.pre_call_hash for item in runtime_evidence.provider_pre_calls],
        transport_anchor_hashes=[
            item.transport_anchor_hash for item in runtime_evidence.transport_anchors
        ],
        provider_attempt_hashes=[item.receipt_hash for item in runtime_evidence.provider_attempts],
        mechanical_transition_hashes=[
            item.receipt_hash for item in runtime_evidence.mechanical_transitions
        ],
        runtime_evidence_hash=runtime_evidence.runtime_evidence_hash,
        complete_budget_replay=True,
        complete_transport_replay=True,
        complete_arm_replay=True,
        complete_mechanical_replay=True,
        hidden_scoring_values_absent=True,
    )


def build_terminal_envelope(
    *,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    entries: Sequence[CellJournalEntry],
    runtime_evidence: CellRuntimeEvidenceBundle,
) -> TerminalEnvelope:
    replay = replay_cell_journal(
        bridge=bridge,
        entries=entries,
        runtime_evidence=runtime_evidence,
    )
    attestation = runtime_evidence.arm_attestation
    provider_attempts = runtime_evidence.provider_attempts
    runtime_failure = any(item.status is ProviderAttemptStatus.FAILED for item in provider_attempts)
    return TerminalEnvelope.create(
        schema_version="adaptive-loop-terminal-envelope-v3",
        receipt_kind="terminal_envelope",
        receipt_bridge_hash=bridge.receipt_bridge_hash,
        cell_binding=attestation.cell_binding,
        attestation_hash=attestation.attestation_hash,
        runtime_evidence_hash=runtime_evidence.runtime_evidence_hash,
        journal_replay_hash=replay.replay_hash,
        journal_entry_count=replay.entry_count,
        journal_head_hash=replay.journal_head_hash,
        budget_ledger_hash=runtime_evidence.budget_ledger.ledger_hash,
        reservation_hashes=replay.reservation_hashes,
        settlement_hashes=replay.settlement_hashes,
        pre_call_hashes=replay.pre_call_hashes,
        transport_anchor_hashes=replay.transport_anchor_hashes,
        provider_attempt_hashes=replay.provider_attempt_hashes,
        mechanical_transition_hashes=replay.mechanical_transition_hashes,
        audit_raw_manifest_sha256=attestation.audit_raw_manifest_sha256,
        controller_visible_manifest_sha256=(attestation.controller_visible_manifest_sha256),
        runtime_failure_recorded=runtime_failure,
        formal_eligible=False,
        process_local_transport_integrity_only=True,
        independently_signed_transport_gateway_verified=False,
        write_once_sealed=True,
        hidden_scoring_values_absent=True,
        scoring_not_executed=True,
        scientific_result_generated=False,
    )


def write_adaptive_loop_benchmark_receipt_bridge_once(
    root: Path | str,
    bundle: AdaptiveLoopBenchmarkExecutionBundle,
) -> AdaptiveLoopBenchmarkReceiptBridge:
    """Validate official fixed paths, then seal the runner-only receipt bridge."""

    bridge = build_adaptive_loop_benchmark_receipt_bridge(bundle)
    _validate_bridge_against_disk(Path(root), bridge)
    _write_contract_once(_bridge_path(Path(root)), bridge)
    return bridge


def load_adaptive_loop_benchmark_receipt_bridge(
    root: Path | str,
) -> AdaptiveLoopBenchmarkReceiptBridge:
    bridge = _read_contract(_bridge_path(Path(root)), AdaptiveLoopBenchmarkReceiptBridge)
    _validate_bridge_against_disk(Path(root), bridge)
    return bridge


def write_cell_runtime_evidence_once(
    root: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    evidence: CellRuntimeEvidenceBundle,
) -> Path:
    _require_disk_bridge(Path(root), bridge)
    _validate_cell_artifacts(bridge, evidence)
    path = _cell_dir(Path(root), evidence.cell_binding.blinded_cell_id) / _RUNTIME_BUNDLE_FILENAME
    _write_contract_once(path, evidence)
    return path


def load_cell_runtime_evidence(
    root: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    blinded_cell_id: str,
) -> CellRuntimeEvidenceBundle:
    _require_disk_bridge(Path(root), bridge)
    path = _cell_dir(Path(root), blinded_cell_id) / _RUNTIME_BUNDLE_FILENAME
    evidence = _read_contract(path, CellRuntimeEvidenceBundle)
    if evidence.cell_binding.blinded_cell_id != blinded_cell_id:
        raise AdaptiveLoopBenchmarkReceiptError("runtime bundle is in another cell path")
    _validate_cell_artifacts(bridge, evidence)
    return evidence


def write_cell_journal_entry_once(
    root: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    entry: CellJournalEntry,
) -> Path:
    _require_binding_in_bridge(bridge, entry.cell_binding)
    directory = _cell_dir(Path(root), entry.cell_binding.blinded_cell_id) / "journal"
    existing = _load_journal_directory(directory, entry.cell_binding.blinded_cell_id)
    if existing:
        _require_same_runtime_identity(entry, existing[-1])
    else:
        evidence = load_cell_runtime_evidence(
            root,
            bridge,
            entry.cell_binding.blinded_cell_id,
        )
        _require_same_runtime_identity(entry, evidence.arm_attestation)
    target = directory / _entry_filename(entry)
    if target.exists():
        _write_contract_once(target, entry)
        return target
    if entry.sequence != len(existing) + 1:
        raise AdaptiveLoopBenchmarkReceiptError(
            "append-only journal cannot skip, insert, or backfill a sequence"
        )
    if existing:
        if entry.previous_entry_hash != existing[-1].entry_hash:
            raise AdaptiveLoopBenchmarkReceiptError(
                "new journal entry does not extend the current head"
            )
    elif entry.previous_entry_hash is not None:
        raise AdaptiveLoopBenchmarkReceiptError("first journal entry has a predecessor")
    _write_contract_once(target, entry)
    return target


def load_cell_journal_entries(
    root: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    blinded_cell_id: str,
) -> list[CellJournalEntry]:
    _require_disk_bridge(Path(root), bridge)
    bridge.cell(blinded_cell_id)
    return _load_journal_directory(
        _cell_dir(Path(root), blinded_cell_id) / "journal",
        blinded_cell_id,
    )


def write_terminal_envelope_once(
    root: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    terminal: TerminalEnvelope,
) -> Path:
    """Replay only on-disk evidence and journal before sealing a terminal."""

    disk_bridge = _require_disk_bridge(Path(root), bridge)
    if disk_bridge != bridge:
        raise AdaptiveLoopBenchmarkReceiptError("supplied bridge differs from disk bridge")
    cell_id = terminal.cell_binding.blinded_cell_id
    cell_dir = _cell_dir(Path(root), cell_id)
    evidence = _read_contract(
        cell_dir / _RUNTIME_BUNDLE_FILENAME,
        CellRuntimeEvidenceBundle,
    )
    _validate_cell_artifacts(bridge, evidence)
    entries = _load_journal_directory(cell_dir / "journal", cell_id)
    expected = build_terminal_envelope(
        bridge=bridge,
        entries=entries,
        runtime_evidence=evidence,
    )
    if terminal != expected:
        raise AdaptiveLoopBenchmarkReceiptError(
            "terminal envelope differs from complete on-disk replay"
        )
    path = _cell_dir(Path(root), cell_id) / _TERMINAL_FILENAME
    _write_contract_once(path, terminal)
    return path


def write_benchmark_terminal_set_seal_once(
    root: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
) -> AdaptiveLoopBenchmarkTerminalSetSeal:
    """Replay and seal the exact 240-cell set; failures remain retained."""

    root_path = Path(root)
    if load_adaptive_loop_benchmark_receipt_bridge(root_path) != bridge:
        raise AdaptiveLoopBenchmarkReceiptError("supplied bridge is not the sealed bridge")
    commitments = _replay_all_sealed_cells(root_path, bridge)
    seal = AdaptiveLoopBenchmarkTerminalSetSeal.create(
        schema_version="adaptive-loop-terminal-set-seal-v3",
        receipt_bridge_hash=bridge.receipt_bridge_hash,
        parent_v1_protocol_hash=bridge.parent_v1_protocol_hash,
        execution_protocol_hash=bridge.execution_protocol_hash,
        public_scenario_panel_hash=bridge.public_scenario_panel_hash,
        blinded_manifest_hash=bridge.blinded_manifest_hash,
        runner_assignment_manifest_hash=bridge.runner_assignment_manifest_hash,
        private_scoring_manifest_hash=bridge.private_scoring_manifest_hash,
        commitments=commitments,
        terminal_envelope_count=240,
        all_terminal_envelopes_write_once=True,
        all_budget_transport_arm_mechanical_evidence_replayed=True,
        reveal_barrier_closed_before_this_seal=True,
        scoring_not_executed=True,
        scientific_result_generated=False,
    )
    _write_contract_once(_terminal_set_path(root_path), seal)
    return seal


def build_blind_reveal_package(
    root: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
) -> AdaptiveLoopBenchmarkBlindRevealPackage:
    """Open scoring input only after revalidating the sealed 240-cell runtime."""

    root_path = Path(root)
    if load_adaptive_loop_benchmark_receipt_bridge(root_path) != bridge:
        raise AdaptiveLoopBenchmarkReceiptError("supplied bridge is not the sealed bridge")
    seal = _read_contract(_terminal_set_path(root_path), AdaptiveLoopBenchmarkTerminalSetSeal)
    replayed = _replay_all_sealed_cells(root_path, bridge)
    expected_seal = AdaptiveLoopBenchmarkTerminalSetSeal.create(
        schema_version="adaptive-loop-terminal-set-seal-v3",
        receipt_bridge_hash=bridge.receipt_bridge_hash,
        parent_v1_protocol_hash=bridge.parent_v1_protocol_hash,
        execution_protocol_hash=bridge.execution_protocol_hash,
        public_scenario_panel_hash=bridge.public_scenario_panel_hash,
        blinded_manifest_hash=bridge.blinded_manifest_hash,
        runner_assignment_manifest_hash=bridge.runner_assignment_manifest_hash,
        private_scoring_manifest_hash=bridge.private_scoring_manifest_hash,
        commitments=replayed,
        terminal_envelope_count=240,
        all_terminal_envelopes_write_once=True,
        all_budget_transport_arm_mechanical_evidence_replayed=True,
        reveal_barrier_closed_before_this_seal=True,
        scoring_not_executed=True,
        scientific_result_generated=False,
    )
    if seal != expected_seal:
        raise AdaptiveLoopBenchmarkReceiptError(
            "terminal set seal differs from fresh complete replay"
        )

    # This is deliberately the first point where private scoring is read.
    scoring = _read_contract(
        _scoring_manifest_path(root_path),
        AdaptiveLoopBenchmarkHiddenOracleManifest,
    )
    _validate_scoring_manifest(bridge, scoring)
    authorization = AdaptiveLoopBenchmarkRevealAuthorization.create(
        schema_version="adaptive-loop-reveal-authorization-v3",
        receipt_bridge_hash=bridge.receipt_bridge_hash,
        terminal_set_hash=seal.terminal_set_hash,
        execution_protocol_hash=bridge.execution_protocol_hash,
        private_scoring_manifest_hash=scoring.hidden_oracle_manifest_hash,
        terminal_envelope_count=240,
        complete_runtime_replay_verified=True,
        reveal_barrier_opened_after_global_seal=True,
        runner_only_scoring_manifest_loaded_after_seal=True,
        scoring_not_executed=True,
        scientific_result_generated=False,
    )
    oracle_by_scenario = {item.scenario_id: item for item in scoring.oracles}
    cells = [
        AdaptiveLoopBenchmarkEvaluatorCellScoreInput(
            cell_binding=item.cell_binding,
            terminal_hash=item.terminal_hash,
            runtime_formal_eligible=item.formal_eligible,
            runtime_failure_recorded=item.runtime_failure_recorded,
            machine_oracle=oracle_by_scenario[item.cell_binding.scenario_id],
            scoring_not_executed=True,
            scientific_result_generated=False,
        )
        for item in seal.commitments
    ]
    score_input = AdaptiveLoopBenchmarkEvaluatorScoreInputManifest.create(
        schema_version="adaptive-loop-evaluator-score-input-manifest-v3",
        authorization_hash=authorization.authorization_hash,
        terminal_set_hash=seal.terminal_set_hash,
        private_scoring_manifest_hash=scoring.hidden_oracle_manifest_hash,
        cells=cells,
        cell_count=240,
        evaluator_only_post_seal=True,
        scoring_not_executed=True,
        score_fields_absent=True,
        scientific_result_generated=False,
    )
    return AdaptiveLoopBenchmarkBlindRevealPackage(
        authorization=authorization,
        score_input=score_input,
    )


def write_blind_reveal_package_once(
    root: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
) -> AdaptiveLoopBenchmarkBlindRevealPackage:
    package = build_blind_reveal_package(root, bridge)
    root_path = Path(root)
    _write_contract_once(_reveal_authorization_path(root_path), package.authorization)
    _write_contract_once(_score_input_path(root_path), package.score_input)
    return package


def _validate_cell_artifacts(
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    evidence: CellRuntimeEvidenceBundle,
) -> None:
    _require_binding_in_bridge(bridge, evidence.cell_binding)
    if evidence.receipt_bridge_hash != bridge.receipt_bridge_hash:
        raise AdaptiveLoopBenchmarkReceiptError("runtime evidence uses another bridge")
    attestation = evidence.arm_attestation
    if attestation.receipt_bridge_hash != bridge.receipt_bridge_hash:
        raise AdaptiveLoopBenchmarkReceiptError("attestation uses another bridge")
    ledger = evidence.budget_ledger
    reservation_by_id = {item.reservation_id: item for item in ledger.reservations}
    settlement_by_id = {item.reservation_id: item for item in ledger.settlements}
    pre_call_by_id = {item.reservation_id: item for item in evidence.provider_pre_calls}
    attempt_by_id = {item.reservation_id: item for item in evidence.provider_attempts}
    anchor_by_id = {item.reservation_id: item for item in evidence.transport_anchors}
    mechanical_by_id = {item.reservation_id: item for item in evidence.mechanical_transitions}
    if len(pre_call_by_id) != len(evidence.provider_pre_calls):
        raise AdaptiveLoopBenchmarkReceiptError("multiple pre-calls share a reservation")
    if len(attempt_by_id) != len(evidence.provider_attempts):
        raise AdaptiveLoopBenchmarkReceiptError("multiple attempts share a reservation")
    if len(anchor_by_id) != len(evidence.transport_anchors):
        raise AdaptiveLoopBenchmarkReceiptError("multiple anchors share a reservation")
    if len(mechanical_by_id) != len(evidence.mechanical_transitions):
        raise AdaptiveLoopBenchmarkReceiptError("multiple mechanics share a reservation")
    if set(pre_call_by_id) != set(attempt_by_id):
        raise AdaptiveLoopBenchmarkReceiptError("every provider attempt needs exactly one pre-call")
    if not set(anchor_by_id).issubset(attempt_by_id):
        raise AdaptiveLoopBenchmarkReceiptError("orphan transport anchor")
    if set(attempt_by_id) & set(mechanical_by_id):
        raise AdaptiveLoopBenchmarkReceiptError("one reservation cannot be provider and mechanical")
    if set(reservation_by_id) != set(attempt_by_id) | set(mechanical_by_id):
        raise AdaptiveLoopBenchmarkReceiptError(
            "every reservation needs exactly one operation receipt"
        )
    scenario = _scenario_for_binding(bridge, evidence.cell_binding)
    expected_stimuli = [item.stimulus_hash for item in scenario.stimuli]
    if len(evidence.mechanical_transitions) != 1:
        raise AdaptiveLoopBenchmarkReceiptError(
            "each cell needs one complete 12-turn mechanical transition"
        )
    for receipt in evidence.mechanical_transitions:
        reservation = reservation_by_id[receipt.reservation_id]
        if reservation.operation_kind is not BudgetOperationKind.MECHANICAL_TRANSITION:
            raise AdaptiveLoopBenchmarkReceiptError(
                "mechanical receipt uses a non-mechanical reservation"
            )
        if receipt.public_stimulus_hashes != expected_stimuli:
            raise AdaptiveLoopBenchmarkReceiptError(
                "mechanical receipt does not commit the official 12 stimuli"
            )
        if settlement_by_id[receipt.reservation_id].evidence_receipt_hash != receipt.receipt_hash:
            raise AdaptiveLoopBenchmarkReceiptError("mechanical settlement binds another receipt")
    for attempt in evidence.provider_attempts:
        reservation = reservation_by_id[attempt.reservation_id]
        pre_call = pre_call_by_id[attempt.reservation_id]
        if reservation.operation_kind not in _MODEL_OPERATION_FIELDS:
            raise AdaptiveLoopBenchmarkReceiptError("provider attempt uses a non-model reservation")
        if (
            pre_call.pre_call_id,
            pre_call.pre_call_hash,
            pre_call.reservation_hash,
        ) != (
            attempt.pre_call_id,
            attempt.pre_call_hash,
            attempt.reservation_hash,
        ):
            raise AdaptiveLoopBenchmarkReceiptError(
                "provider attempt does not bind its exact pre-call"
            )
        anchor = anchor_by_id.get(attempt.reservation_id)
        if (attempt.external_transport_anchor is None) != (anchor is None):
            raise AdaptiveLoopBenchmarkReceiptError(
                "provider embedded/external anchor coverage differs"
            )
        if anchor is not None and attempt.external_transport_anchor != anchor:
            raise AdaptiveLoopBenchmarkReceiptError(
                "provider embedded transport anchor differs from runtime anchor"
            )
        if settlement_by_id[attempt.reservation_id].evidence_receipt_hash != attempt.receipt_hash:
            raise AdaptiveLoopBenchmarkReceiptError("provider settlement binds another attempt")


def _replay_all_sealed_cells(
    root: Path,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
) -> list[CellTerminalCommitment]:
    expected_ids = [item.blinded_cell_id for item in bridge.cells]
    cells_root = _cells_root(root)
    if not cells_root.is_dir():
        raise AdaptiveLoopBenchmarkReceiptError("runtime cell directory is missing")
    actual_dirs = sorted(item.name for item in cells_root.iterdir() if item.is_dir())
    if actual_dirs != sorted(expected_ids):
        raise AdaptiveLoopBenchmarkReceiptError(
            "runtime cell paths do not equal the official 240-cell set"
        )
    unexpected_files = [item for item in cells_root.iterdir() if not item.is_dir()]
    if unexpected_files:
        raise AdaptiveLoopBenchmarkReceiptError("unexpected file in runtime cells root")
    commitments: list[CellTerminalCommitment] = []
    for binding in bridge.cells:
        cell_dir = _cell_dir(root, binding.blinded_cell_id)
        allowed = {_RUNTIME_BUNDLE_FILENAME, _TERMINAL_FILENAME, "journal"}
        if {item.name for item in cell_dir.iterdir()} != allowed:
            raise AdaptiveLoopBenchmarkReceiptError(
                f"cell {binding.blinded_cell_id} has missing or unexpected artifacts"
            )
        evidence = _read_contract(
            cell_dir / _RUNTIME_BUNDLE_FILENAME,
            CellRuntimeEvidenceBundle,
        )
        _validate_cell_artifacts(bridge, evidence)
        entries = _load_journal_directory(
            cell_dir / "journal",
            binding.blinded_cell_id,
        )
        terminal = _read_contract(cell_dir / _TERMINAL_FILENAME, TerminalEnvelope)
        expected_terminal = build_terminal_envelope(
            bridge=bridge,
            entries=entries,
            runtime_evidence=evidence,
        )
        if terminal != expected_terminal:
            raise AdaptiveLoopBenchmarkReceiptError(
                f"cell {binding.blinded_cell_id} terminal differs from replay"
            )
        replay = replay_cell_journal(
            bridge=bridge,
            entries=entries,
            runtime_evidence=evidence,
        )
        commitments.append(
            CellTerminalCommitment.create(
                schema_version="adaptive-loop-cell-terminal-commitment-v3",
                cell_binding=binding,
                terminal_hash=terminal.terminal_hash,
                runtime_evidence_hash=evidence.runtime_evidence_hash,
                journal_replay_hash=replay.replay_hash,
                formal_eligible=terminal.formal_eligible,
                runtime_failure_recorded=terminal.runtime_failure_recorded,
            )
        )
    return commitments


def _validate_bridge_against_disk(
    root: Path,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
) -> None:
    protocol = _read_contract(
        root / _PUBLIC_PROTOCOL_FILENAME, AdaptiveLoopBenchmarkExecutionProtocol
    )
    blinded = _read_contract(
        root / _BLINDED_MANIFEST_FILENAME, AdaptiveLoopBenchmarkBlindedCellManifest
    )
    runner = _read_contract(
        root / "runner-only" / _RUNNER_MANIFEST_FILENAME,
        AdaptiveLoopBenchmarkRunnerAssignmentManifest,
    )
    if (
        bridge.execution_protocol,
        bridge.blinded_manifest,
        bridge.runner_assignment_manifest,
    ) != (protocol, blinded, runner):
        raise AdaptiveLoopBenchmarkReceiptError(
            "receipt bridge differs from official fixed-path v3 artifacts"
        )


def _require_disk_bridge(
    root: Path,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
) -> AdaptiveLoopBenchmarkReceiptBridge:
    path = _bridge_path(root)
    expected = (canonical_json(bridge) + "\n").encode("utf-8")
    if not path.is_file() or path.read_bytes() != expected:
        raise AdaptiveLoopBenchmarkReceiptError(
            "supplied bridge is not the exact write-once disk bridge"
        )
    return bridge


def _validate_scoring_manifest(
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    scoring: AdaptiveLoopBenchmarkHiddenOracleManifest,
) -> None:
    if (
        scoring.hidden_oracle_manifest_hash,
        scoring.parent_v1_protocol_hash,
        scoring.public_scenario_panel_hash,
    ) != (
        bridge.private_scoring_manifest_hash,
        bridge.parent_v1_protocol_hash,
        bridge.public_scenario_panel_hash,
    ):
        raise AdaptiveLoopBenchmarkReceiptError(
            "post-seal private scoring manifest does not match the bridge"
        )
    expected = {
        (item.scenario_id, item.public_scenario_hash)
        for item in bridge.execution_protocol.public_scenarios
    }
    actual = {(item.scenario_id, item.public_scenario_hash) for item in scoring.oracles}
    if actual != expected:
        raise AdaptiveLoopBenchmarkReceiptError(
            "post-seal oracle panel does not match public scenarios"
        )


def _require_binding_in_bridge(
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
) -> None:
    if bridge.cell(binding.blinded_cell_id) != binding:
        raise AdaptiveLoopBenchmarkReceiptError(
            "runtime cell binding differs from the official bridge leaf"
        )


def _scenario_for_binding(
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
) -> AdaptiveLoopBenchmarkPublicScenario:
    _require_binding_in_bridge(bridge, binding)
    for scenario in bridge.execution_protocol.public_scenarios:
        if scenario.scenario_id == binding.scenario_id:
            if scenario.public_scenario_hash != binding.public_scenario_hash:
                raise AdaptiveLoopBenchmarkReceiptError("binding public scenario hash mismatch")
            return scenario
    raise AdaptiveLoopBenchmarkReceiptError("binding scenario is absent")


def _verify_journal_chain(entries: Sequence[CellJournalEntry]) -> None:
    if not entries:
        raise AdaptiveLoopBenchmarkReceiptError("cell journal is empty")
    for expected_sequence, entry in enumerate(entries, start=1):
        if entry.sequence != expected_sequence:
            raise AdaptiveLoopBenchmarkReceiptError(
                "journal sequence was deleted, inserted, or reordered"
            )
        expected_previous = (
            None if expected_sequence == 1 else entries[expected_sequence - 2].entry_hash
        )
        if entry.previous_entry_hash != expected_previous:
            raise AdaptiveLoopBenchmarkReceiptError("journal forward hash chain is broken")


def _load_journal_directory(directory: Path, blinded_cell_id: str) -> list[CellJournalEntry]:
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise AdaptiveLoopBenchmarkReceiptError("journal path is not a directory")
    paths = sorted(directory.iterdir())
    entries: list[CellJournalEntry] = []
    for expected, path in enumerate(paths, start=1):
        match = re.fullmatch(r"entry-(\d{6})-([0-9a-f]{64})\.json", path.name)
        if path.is_dir() or match is None:
            raise AdaptiveLoopBenchmarkReceiptError("unexpected journal path")
        if int(match.group(1)) != expected:
            raise AdaptiveLoopBenchmarkReceiptError("journal file sequence has a gap")
        entry = _read_contract(path, CellJournalEntry)
        if entry.sequence != expected or entry.entry_hash != match.group(2):
            raise AdaptiveLoopBenchmarkReceiptError("journal filename/content mismatch")
        if entry.cell_binding.blinded_cell_id != blinded_cell_id:
            raise AdaptiveLoopBenchmarkReceiptError("cross-cell journal substitution")
        entries.append(entry)
    _verify_journal_chain(entries) if entries else None
    return entries


def _validate_runtime_identity(
    item: Any, binding: AdaptiveLoopBenchmarkCellExecutionBinding
) -> None:
    if item.trajectory_id != _trajectory_id(binding):
        raise ValueError("runtime receipt trajectory does not match its cell binding")


def _require_same_runtime_identity(left: Any, right: Any) -> None:
    left_binding = left.cell_binding
    right_binding = right.cell_binding
    if (
        left_binding,
        left.trajectory_id,
        left.attestation_hash,
    ) != (
        right_binding,
        right.trajectory_id,
        right.attestation_hash,
    ):
        raise AdaptiveLoopBenchmarkReceiptError(
            "cross-cell, cross-arm, or cross-trajectory artifact substitution"
        )


def _frozen_arm_profile(arm: AdaptiveLoopBenchmarkArm) -> AdaptiveLoopBenchmarkArmSpec:
    protocol = build_adaptive_loop_benchmark_protocol()
    for item in protocol.arms:
        if item.arm is arm:
            return item
    raise AdaptiveLoopBenchmarkReceiptError(f"unknown benchmark arm: {arm.value}")


def _trajectory_id(binding: AdaptiveLoopBenchmarkCellExecutionBinding) -> str:
    return f"trajectory-v3:{binding.cell_binding_hash}"


def _charged_from_reservation(
    reservation: BudgetReservation,
    wall_time_milliseconds: int,
) -> BudgetVector:
    values = reservation.reserved.model_dump(mode="json")
    values["wall_time_milliseconds"] = wall_time_milliseconds
    return BudgetVector.model_validate(values)


def _sum_vectors(vectors: Iterable[BudgetVector]) -> BudgetVector:
    total = BudgetVector()
    for item in vectors:
        total = total.add(item)
    return total


def _vector_nonzero(vector: BudgetVector) -> bool:
    return any(
        int(getattr(vector, name)) != 0 for name in (*_COUNT_FIELDS, "wall_time_milliseconds")
    )


def _require_unique_hashes(values: Sequence[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} hashes must be unique")


def _calculated_hash(contract: KernelContract, hash_field: str) -> str:
    return canonical_sha256(contract.model_dump(mode="json", exclude={hash_field}))


def _addressed(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    normalized = _json_compatible(payload)
    if not isinstance(normalized, dict):
        raise TypeError("addressed receipt payload must be an object")
    normalized[hash_field] = canonical_sha256(normalized)
    return normalized


def _json_compatible(value: Any) -> Any:
    if isinstance(value, KernelContract):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_compatible(item) for item in value]
    return value


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _optional_sha256(payload: bytes | None) -> str | None:
    return None if payload is None else _sha256_bytes(payload)


def _entry_filename(entry: CellJournalEntry) -> str:
    return f"entry-{entry.sequence:06d}-{entry.entry_hash}.json"


def _runner_root(root: Path) -> Path:
    return root.resolve() / "runner-only"


def _bridge_path(root: Path) -> Path:
    return _runner_root(root) / _BRIDGE_FILENAME


def _cells_root(root: Path) -> Path:
    return _runner_root(root) / "runtime-receipts" / "cells"


def _cell_dir(root: Path, blinded_cell_id: str) -> Path:
    if _CELL_ID_PATTERN.fullmatch(blinded_cell_id) is None:
        raise AdaptiveLoopBenchmarkReceiptError("unsafe or obsolete cell path identity")
    base = _cells_root(root).resolve()
    path = (base / blinded_cell_id).resolve()
    if path.parent != base:
        raise AdaptiveLoopBenchmarkReceiptError("cell path escapes runtime receipt root")
    return path


def _scoring_manifest_path(root: Path) -> Path:
    return _runner_root(root) / _SCORING_MANIFEST_FILENAME


def _terminal_set_path(root: Path) -> Path:
    return _runner_root(root) / "runtime-receipts" / _TERMINAL_SET_FILENAME


def _reveal_authorization_path(root: Path) -> Path:
    return root.resolve() / "evaluator-only" / "post-seal" / _REVEAL_AUTH_FILENAME


def _score_input_path(root: Path) -> Path:
    return root.resolve() / "evaluator-only" / "post-seal" / _SCORE_INPUT_FILENAME


TContract = TypeVar("TContract", bound=KernelContract)


def _read_contract(path: Path, contract_type: type[TContract]) -> TContract:
    if not path.is_file():
        raise AdaptiveLoopBenchmarkReceiptError(f"required fixed-path artifact missing: {path}")
    try:
        payload = path.read_bytes()
        contract = contract_type.model_validate_json(payload)
    except (OSError, ValueError) as exc:
        raise AdaptiveLoopBenchmarkReceiptError(
            f"invalid immutable artifact at {path}: {exc}"
        ) from exc
    expected = (canonical_json(contract) + "\n").encode("utf-8")
    if payload != expected:
        raise AdaptiveLoopBenchmarkReceiptError(
            f"artifact is not canonical or has trailing/mutable bytes: {path}"
        )
    return contract


def _write_contract_once(path: Path, contract: KernelContract) -> None:
    payload = (canonical_json(contract) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise AdaptiveLoopBenchmarkReceiptError(
                f"write-once artifact already exists with different bytes: {path}"
            )
        return
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        if not path.is_file() or path.read_bytes() != payload:
            raise AdaptiveLoopBenchmarkReceiptError(
                f"concurrent write changed write-once artifact: {path}"
            ) from exc
