"""Signed-gateway, result-blind live runner for one protocol-v3 cell.

This module is deliberately a sibling of the local diagnostic runner.  It never
loads a hidden oracle or scores an answer.  Every model request is committed only
after the generic loop has written its immutable action-call registration and is
then sent through an independently operated, Ed25519-signed gateway.  The runner
never accepts a gateway private key, never calls the ordinary process-local LLM
client, and never promotes a process-local HTTP trace into formal evidence.

The signed gateway is verified immediately while its receipt is fresh and its
nonce is consumed once.  Terminal replay rechecks the signature, external trust
policy, original freshness, and local anti-replay entry without consuming the
nonce again.  That local ledger is integrity state, not an independent source of
identity or acceptance.  A zero-network signed test double is supported only on an
explicitly non-confirmatory track and can never produce a formally eligible cell.

The Python API cannot prove that its caller obtained key/build/source pins through
an out-of-band operator channel, nor that ``test_only=False`` describes a genuinely
independent deployment.  Consequently ``formal_eligible`` is always conditional:
the cryptographic chain is valid *under the supplied pins*.  Establishing the pins'
external provenance remains an operator/deployment obligation, without inventing a
second signer inside this runner.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import time
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult, reasoning_transport_for_provider
from autoresearch.research import adaptive_loop_benchmark_arm_adapters as arm_module
from autoresearch.research import adaptive_loop_benchmark_context as context_module
from autoresearch.research import adaptive_loop_benchmark_receipts as receipt_module
from autoresearch.research import adaptive_sovereign_loop as loop_module
from autoresearch.research import adaptive_sovereign_recall_use as recall_use_module
from autoresearch.research import adaptive_transport_gateway as gateway_module
from autoresearch.research import adaptive_transport_gateway_worker as gateway_worker_module
from autoresearch.research.adaptive_capabilities import AdaptiveResearchCapabilityEnvironment
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_benchmark_arm_adapters import (
    BenchmarkArmRealizationAudit,
    BenchmarkArmRuntimePlan,
    audit_benchmark_arm_realization,
    build_benchmark_arm_adapter,
)
from autoresearch.research.adaptive_loop_benchmark_context import (
    AdaptiveLoopBenchmarkPublicContextAdapter,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkBlindedCell,
    AdaptiveLoopBenchmarkPublicScenario,
)
from autoresearch.research.adaptive_loop_benchmark_receipts import (
    AdaptiveLoopBenchmarkCellExecutionBinding,
    AdaptiveLoopBenchmarkReceiptBridge,
    ArmRuntimeAttestation,
    BudgetLedger,
    BudgetLedgerEntry,
    BudgetOperationKind,
    BudgetOutcome,
    BudgetReservation,
    BudgetVector,
    build_arm_runtime_attestation,
    build_budget_ledger,
    build_budget_ledger_entry,
    build_budget_reservation,
    load_adaptive_loop_benchmark_receipt_bridge,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveActionModelCallRegistration,
    AdaptiveLoopPolicy,
    AdaptiveLoopRunStatus,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    ModelResearchActionDraft,
    ResearchOperator,
    TemporaryAgentBatchOutcome,
    TemporaryResearchTask,
    load_adaptive_research_loop_snapshot,
    run_adaptive_research_loop,
)
from autoresearch.research.adaptive_sovereign_recall_use import (
    SovereignRecallGatewayVerificationPolicy,
    SovereignRecallUseAuditError,
    SovereignRecallUseReceipt,
    SovereignRecallVerifiedGatewayExchange,
    audit_sovereign_recall_use,
)
from autoresearch.research.adaptive_transport_gateway import (
    AdaptiveTransportGatewayReceipt,
    AdaptiveTransportRequestCommitment,
    PostRunAdaptiveTransportGatewayReplay,
    SignedAdaptiveTransportGatewayReceipt,
    TransportGatewayReplayLedger,
    VerifiedAdaptiveTransportGatewayAttestation,
    build_transport_gateway_request_commitment,
    replay_verify_adaptive_transport_gateway_attestation,
    verify_adaptive_transport_gateway_receipt,
)
from autoresearch.research.adaptive_transport_gateway_worker import (
    AdaptiveTransportGatewayWorkerRequest,
    build_adaptive_transport_gateway_worker_request,
    load_adaptive_transport_gateway_worker_output,
)

_TURN_COUNT = 12
_MODEL_RESERVATION_MILLISECONDS = 300_000
_SPEC_FILENAME = "formal-benchmark-cell-run-spec-v1.json"
_ARTIFACT_FILENAME = "formal-benchmark-cell-run-artifact-v1.json"
_SOURCE_MODULES: dict[str, Any] = {
    "adaptive_loop_benchmark_live_runner": None,
    "adaptive_loop_benchmark_arm_adapters": arm_module,
    "adaptive_loop_benchmark_context": context_module,
    "adaptive_loop_benchmark_receipts": receipt_module,
    "adaptive_sovereign_loop": loop_module,
    "adaptive_sovereign_recall_use": recall_use_module,
    "adaptive_transport_gateway": gateway_module,
    "adaptive_transport_gateway_worker": gateway_worker_module,
}


class AdaptiveLoopBenchmarkLiveRunError(RuntimeError):
    """Raised when a live cell cannot retain a trustworthy signed trajectory."""


class FormalLiveExecutionTrack(str, Enum):
    EXTERNAL_SIGNED_GATEWAY = "external_signed_gateway"
    ZERO_NETWORK_SIGNED_TEST_DOUBLE = "zero_network_signed_test_double"


class FormalLiveCallOutcome(str, Enum):
    PROVIDER_COMPLETION = "provider_completion"
    SIGNED_RESPONSE_VALIDATION_FAILURE = "signed_response_validation_failure"
    SIGNED_HTTP_FAILURE = "signed_http_failure"
    SIGNED_TRANSPORT_FAILURE = "signed_transport_failure"
    UNVERIFIED_GATEWAY_FAILURE = "unverified_gateway_failure"


class SignedGatewayTransport(Protocol):
    """Command/service boundary whose independent deployment is operator-proven."""

    test_only: bool

    def __call__(self, canonical_worker_request: bytes) -> bytes: ...


class FormalGatewayTrustPolicyContent(KernelContract):
    schema_version: Literal["formal-benchmark-gateway-trust-policy-v1"] = (
        "formal-benchmark-gateway-trust-policy-v1"
    )
    provider_name: Literal["qwen"] = "qwen"
    model_name: StableId
    request_url: str = Field(min_length=1, max_length=2_048)
    allowlisted_origins: tuple[str, ...] = Field(min_length=1, max_length=8)
    trusted_gateway_public_key_sha256: Sha256
    trusted_gateway_build_sha256: Sha256
    trusted_gateway_source_sha256: Sha256
    max_redirects: int = Field(default=0, ge=0, le=3)
    gateway_private_key_available_to_runner: Literal[False] = False
    gateway_private_key_loaded_by_runner: Literal[False] = False
    process_local_trace_is_formal_evidence: Literal[False] = False
    supplied_pins_require_out_of_band_operator_provenance: Literal[True] = True
    python_api_verified_pin_provenance: Literal[False] = False
    test_only_false_is_external_provenance: Literal[False] = False

    @field_validator("model_name")
    @classmethod
    def _require_qwen_model(cls, value: str) -> str:
        if "qwen" not in value.casefold():
            raise ValueError("formal benchmark model must be explicitly Qwen")
        return value

    @field_validator("allowlisted_origins")
    @classmethod
    def _require_unique_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(value))) != value:
            raise ValueError("gateway origins must be sorted and unique")
        return value


class FormalGatewayTrustPolicy(FormalGatewayTrustPolicyContent):
    policy_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> FormalGatewayTrustPolicy:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"policy_hash"}))
        if self.policy_hash != expected:
            raise ValueError("formal gateway trust-policy hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FormalGatewayTrustPolicy:
        content = FormalGatewayTrustPolicyContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, policy_hash=canonical_sha256(payload))


class FormalCellManifestEntry(KernelContract):
    entry_id: str = Field(min_length=1, max_length=2_048)
    content_sha256: Sha256


class FormalCellEvidenceManifest(KernelContract):
    schema_version: Literal["formal-benchmark-cell-evidence-manifest-v1"] = (
        "formal-benchmark-cell-evidence-manifest-v1"
    )
    plane: Literal["audit_raw", "controller_visible"]
    cell_binding_hash: Sha256
    entries: list[FormalCellManifestEntry] = Field(min_length=1, max_length=512)
    entry_count: int = Field(ge=1, le=512)
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> FormalCellEvidenceManifest:
        if self.entry_count != len(self.entries):
            raise ValueError("formal cell manifest count mismatch")
        if len({item.entry_id for item in self.entries}) != len(self.entries):
            raise ValueError("formal cell manifest repeats an entry ID")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))
        if self.manifest_hash != expected:
            raise ValueError("formal cell manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FormalCellEvidenceManifest:
        payload = {"schema_version": "formal-benchmark-cell-evidence-manifest-v1", **values}
        payload["entries"] = [
            item.model_dump(mode="json") if isinstance(item, FormalCellManifestEntry) else item
            for item in payload["entries"]
        ]
        return cls(**payload, manifest_hash=canonical_sha256(payload))


class FormalBenchmarkCellRunSpecContent(KernelContract):
    """All public lineage and external trust inputs sealed before provider use."""

    schema_version: Literal["formal-benchmark-cell-run-spec-v1"] = (
        "formal-benchmark-cell-run-spec-v1"
    )
    execution_track: FormalLiveExecutionTrack
    receipt_bridge_hash: Sha256
    public_scenario: AdaptiveLoopBenchmarkPublicScenario
    blinded_cell: AdaptiveLoopBenchmarkBlindedCell
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    arm_runtime_plan: BenchmarkArmRuntimePlan
    seed: AdaptiveResearchSeed
    policy: AdaptiveLoopPolicy
    seed_sha256: Sha256
    policy_sha256: Sha256
    gateway_trust_policy: FormalGatewayTrustPolicy
    initial_audit_raw_plane_id: StableId
    initial_controller_visible_plane_id: StableId
    initial_audit_raw_plane_manifest_sha256: Sha256
    initial_controller_visible_plane_manifest_sha256: Sha256
    budget_limit: BudgetVector
    source_module_sha256s: dict[str, Sha256]
    hidden_scoring_loaded: Literal[False] = False
    scoring_requested: Literal[False] = False
    scientific_result_requested: Literal[False] = False
    independent_signed_gateway_required: Literal[True] = True
    formal_eligibility_is_conditional_on_supplied_pins: Literal[True] = True

    @field_validator("source_module_sha256s")
    @classmethod
    def _validate_source_inventory(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != set(_SOURCE_MODULES):
            raise ValueError("formal runner source-module inventory is incomplete")
        return value

    @model_validator(mode="after")
    def _validate_spec(self) -> FormalBenchmarkCellRunSpecContent:
        if self.seed_sha256 != canonical_sha256(self.seed):
            raise ValueError("formal cell seed hash mismatch")
        if self.policy_sha256 != canonical_sha256(self.policy):
            raise ValueError("formal cell policy hash mismatch")
        if self.policy.max_steps != _TURN_COUNT or self.policy.max_model_calls != _TURN_COUNT:
            raise ValueError("formal cell requires exactly twelve steps/model calls")
        if self.seed.objective_cn != self.public_scenario.objective_cn:
            raise ValueError("formal cell objective differs from public scenario")
        if self.seed.scope_cn != self.public_scenario.scope_cn:
            raise ValueError("formal cell scope differs from public scenario")
        if (
            self.blinded_cell.blinded_cell_id != self.cell_binding.blinded_cell_id
            or self.blinded_cell.scenario_id != self.cell_binding.scenario_id
            or self.blinded_cell.public_scenario_hash != self.cell_binding.public_scenario_hash
        ):
            raise ValueError("formal blinded cell and runner binding disagree")
        if (
            self.public_scenario.scenario_id != self.cell_binding.scenario_id
            or self.public_scenario.public_scenario_hash != self.cell_binding.public_scenario_hash
        ):
            raise ValueError("formal public scenario and runner binding disagree")
        if self.arm_runtime_plan.arm is not self.cell_binding.arm:
            raise ValueError("formal arm plan differs from runner assignment")
        expected_budget = BudgetVector(
            main_model_requests=_TURN_COUNT,
            wall_time_milliseconds=_TURN_COUNT * _MODEL_RESERVATION_MILLISECONDS,
        )
        if self.budget_limit != expected_budget:
            raise ValueError("formal cell budget differs from the frozen twelve-call budget")
        if self.initial_audit_raw_plane_id == self.initial_controller_visible_plane_id:
            raise ValueError("formal raw/controller planes must differ")
        return self


class FormalBenchmarkCellRunSpec(FormalBenchmarkCellRunSpecContent):
    spec_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> FormalBenchmarkCellRunSpec:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"spec_hash"}))
        if self.spec_hash != expected:
            raise ValueError("formal benchmark cell spec hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FormalBenchmarkCellRunSpec:
        content = FormalBenchmarkCellRunSpecContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, spec_hash=canonical_sha256(payload))


class FormalGatewayCallEvidenceContent(KernelContract):
    schema_version: Literal["formal-benchmark-gateway-call-evidence-v1"] = (
        "formal-benchmark-gateway-call-evidence-v1"
    )
    spec_hash: Sha256
    call_index: int = Field(ge=1, le=_TURN_COUNT)
    step_index: int = Field(ge=1, le=_TURN_COUNT)
    attempt_index: int = Field(ge=1, le=3)
    registration: AdaptiveActionModelCallRegistration
    reservation: BudgetReservation
    request_messages: list[dict[Literal["role", "content"], str]] = Field(min_length=2)
    request_messages_sha256: Sha256
    request_commitment: AdaptiveTransportRequestCommitment
    worker_request: AdaptiveTransportGatewayWorkerRequest
    worker_request_hash: Sha256
    gateway_worker_stdout_sha256: Sha256 | None = None
    signed_receipt: SignedAdaptiveTransportGatewayReceipt | None = None
    accepted_attestation: VerifiedAdaptiveTransportGatewayAttestation | None = None
    completion_payload_hash: Sha256 | None = None
    outcome: FormalLiveCallOutcome
    operation_started: Literal[True] = True
    charged_even_when_failed: Literal[True] = True
    external_gateway_signature_verified: bool
    provider_completion_eligible: bool
    process_local_trace_used_for_formality: Literal[False] = False
    failure_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _validate_evidence(self) -> FormalGatewayCallEvidenceContent:
        commitment = self.request_commitment
        if (self.step_index, self.attempt_index) != (
            self.registration.step_index,
            self.registration.attempt_index,
        ):
            raise ValueError("gateway call index differs from its action registration")
        if (
            self.request_messages_sha256 != canonical_sha256(self.request_messages)
            or self.request_messages_sha256 != self.registration.messages_sha256
        ):
            raise ValueError("gateway evidence changed the exact action messages")
        if (
            self.worker_request.request_commitment != commitment
            or self.worker_request.worker_request_hash != self.worker_request_hash
        ):
            raise ValueError("gateway worker request differs from retained call evidence")
        try:
            request_payload = json.loads(self.worker_request.request_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("gateway request payload is not UTF-8 JSON") from exc
        if (
            not isinstance(request_payload, dict)
            or request_payload.get("messages") != self.request_messages
        ):
            raise ValueError("gateway request bytes differ from exact action messages")
        if (
            commitment.cell_id != self.reservation.cell_binding.blinded_cell_id
            or commitment.trajectory_id != self.reservation.trajectory_id
        ):
            raise ValueError("gateway call crosses its reserved cell trajectory")
        if (
            commitment.pre_call_id,
            commitment.pre_call_hash,
            commitment.reservation_id,
            commitment.reservation_hash,
            commitment.request_messages_sha256,
        ) != (
            self.registration.registration_id,
            self.registration.registration_hash,
            self.reservation.reservation_id,
            self.reservation.reservation_hash,
            self.registration.messages_sha256,
        ):
            raise ValueError("gateway call does not bind registration/reservation/messages")
        verified = self.accepted_attestation is not None
        if self.external_gateway_signature_verified != verified:
            raise ValueError("gateway call signature verdict mismatch")
        if verified:
            assert self.signed_receipt is not None
            attestation = self.accepted_attestation
            assert attestation is not None
            if (
                attestation.receipt_hash != self.signed_receipt.receipt.receipt_hash
                or attestation.envelope_hash != self.signed_receipt.envelope_hash
                or attestation.request_commitment_hash != commitment.commitment_hash
            ):
                raise ValueError("gateway attestation binds another exchange")
            if self.provider_completion_eligible != attestation.provider_completion_eligible:
                raise ValueError("gateway call completion verdict mismatch")
            if not attestation.formal_transport_eligible:
                raise ValueError("accepted gateway signature is not formal transport evidence")
        elif self.signed_receipt is not None:
            raise ValueError("unverified signed receipt cannot be retained as accepted evidence")
        if verified and self.gateway_worker_stdout_sha256 is None:
            raise ValueError("verified gateway exchange lacks exact worker-output hash")
        if self.outcome is FormalLiveCallOutcome.PROVIDER_COMPLETION:
            if not verified or not self.provider_completion_eligible:
                raise ValueError("provider completion lacks an accepted signed gateway receipt")
            if self.completion_payload_hash is None or self.failure_sha256 is not None:
                raise ValueError("provider completion payload/failure fields disagree")
        elif self.outcome is FormalLiveCallOutcome.SIGNED_RESPONSE_VALIDATION_FAILURE:
            if not verified or not self.provider_completion_eligible:
                raise ValueError("response-validation failure lacks a signed completion")
            if self.completion_payload_hash is None or self.failure_sha256 is None:
                raise ValueError("response-validation failure evidence is incomplete")
        else:
            if self.completion_payload_hash is not None or self.failure_sha256 is None:
                raise ValueError("failed gateway call must retain only a failure hash")
        return self


class FormalGatewayCallEvidence(FormalGatewayCallEvidenceContent):
    evidence_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> FormalGatewayCallEvidence:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"evidence_hash"}))
        if self.evidence_hash != expected:
            raise ValueError("formal gateway call-evidence hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FormalGatewayCallEvidence:
        content = FormalGatewayCallEvidenceContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, evidence_hash=canonical_sha256(payload))


class FormalBenchmarkCellTerminalContent(KernelContract):
    schema_version: Literal["formal-benchmark-cell-terminal-v1"] = (
        "formal-benchmark-cell-terminal-v1"
    )
    spec_hash: Sha256
    snapshot_hash: Sha256
    arm_audit_hash: Sha256
    budget_ledger_hash: Sha256
    call_evidence_hashes: list[Sha256] = Field(min_length=_TURN_COUNT, max_length=_TURN_COUNT)
    post_run_gateway_replay_hashes: list[Sha256] = Field(
        min_length=_TURN_COUNT,
        max_length=_TURN_COUNT,
    )
    sovereign_recall_use_receipt_hash: Sha256 | None = None
    all_twelve_provider_completions_verified: Literal[True] = True
    all_twelve_gateway_signatures_and_local_antireplay_replayed: Literal[True] = True
    local_antireplay_ledger_is_independent_acceptance_evidence: Literal[False] = False
    actual_sovereign_recall_use_verified: bool
    arm: AdaptiveLoopBenchmarkArm
    execution_track: FormalLiveExecutionTrack
    formal_eligible: bool
    hidden_scoring_loaded: Literal[False] = False
    scoring_not_executed: Literal[True] = True
    scientific_result_generated: Literal[False] = False
    publication_authorized: Literal[False] = False
    eligibility_is_conditional_on_supplied_pin_provenance: Literal[True] = True
    python_api_verified_pin_provenance: Literal[False] = False

    @model_validator(mode="after")
    def _validate_terminal(self) -> FormalBenchmarkCellTerminalContent:
        sovereign = self.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        if sovereign != self.actual_sovereign_recall_use_verified:
            raise ValueError("A4 terminal requires actual sovereign-recall use")
        if sovereign != (self.sovereign_recall_use_receipt_hash is not None):
            raise ValueError("A4 terminal sovereign-use receipt presence mismatch")
        expected_formal = self.execution_track is FormalLiveExecutionTrack.EXTERNAL_SIGNED_GATEWAY
        if self.formal_eligible != expected_formal:
            raise ValueError("formal terminal eligibility was not mechanically derived")
        return self


class FormalBenchmarkCellTerminal(FormalBenchmarkCellTerminalContent):
    terminal_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> FormalBenchmarkCellTerminal:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"terminal_hash"}))
        if self.terminal_hash != expected:
            raise ValueError("formal benchmark terminal hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FormalBenchmarkCellTerminal:
        content = FormalBenchmarkCellTerminalContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, terminal_hash=canonical_sha256(payload))


class FormalBenchmarkCellRunArtifactContent(KernelContract):
    schema_version: Literal["formal-benchmark-cell-run-artifact-v1"] = (
        "formal-benchmark-cell-run-artifact-v1"
    )
    run_spec: FormalBenchmarkCellRunSpec
    final_snapshot: AdaptiveResearchLoopSnapshot
    call_evidence: list[FormalGatewayCallEvidence] = Field(min_length=1, max_length=_TURN_COUNT)
    budget_ledger: BudgetLedger
    post_run_gateway_replays: list[PostRunAdaptiveTransportGatewayReplay] = Field(
        max_length=_TURN_COUNT
    )
    arm_realization_audit: BenchmarkArmRealizationAudit | None = None
    audit_raw_final_manifest: FormalCellEvidenceManifest | None = None
    controller_visible_final_manifest: FormalCellEvidenceManifest | None = None
    sovereign_recall_use_receipt: SovereignRecallUseReceipt | None = None
    terminal: FormalBenchmarkCellTerminal | None = None
    runtime_failure_sha256: Sha256 | None = None
    formal_eligible: bool
    test_only_non_confirmatory: bool
    hidden_scoring_loaded: Literal[False] = False
    scoring_not_executed: Literal[True] = True
    scientific_result_generated: Literal[False] = False
    publication_authorized: Literal[False] = False
    eligibility_is_conditional_on_supplied_pin_provenance: Literal[True] = True
    python_api_verified_pin_provenance: Literal[False] = False

    @model_validator(mode="after")
    def _validate_artifact(self) -> FormalBenchmarkCellRunArtifactContent:
        spec = self.run_spec
        if self.final_snapshot.seed != spec.seed or self.final_snapshot.policy != spec.policy:
            raise ValueError("formal artifact snapshot differs from sealed seed/policy")
        if [item.call_index for item in self.call_evidence] != list(
            range(1, len(self.call_evidence) + 1)
        ):
            raise ValueError("formal call evidence order is not contiguous")
        trajectory_id = self.budget_ledger.trajectory_id
        if (
            self.budget_ledger.cell_binding != spec.cell_binding
            or self.budget_ledger.budget_limit != spec.budget_limit
        ):
            raise ValueError("formal budget ledger belongs to another sealed cell")
        for evidence in self.call_evidence:
            commitment = evidence.request_commitment
            if evidence.spec_hash != spec.spec_hash:
                raise ValueError("formal call evidence binds another run spec")
            if (
                evidence.registration.loop_id != spec.seed.loop_id
                or evidence.registration.project_id != spec.seed.project_id
            ):
                raise ValueError("formal call registration belongs to another loop")
            if (
                evidence.reservation.cell_binding != spec.cell_binding
                or evidence.reservation.trajectory_id != trajectory_id
            ):
                raise ValueError("formal call reservation crosses cell trajectory")
            if (
                commitment.provider_name != spec.gateway_trust_policy.provider_name
                or commitment.model_name != spec.gateway_trust_policy.model_name
                or commitment.request_url != spec.gateway_trust_policy.request_url
                or commitment.request_origin not in spec.gateway_trust_policy.allowlisted_origins
                or commitment.cell_id != spec.cell_binding.blinded_cell_id
                or commitment.trajectory_id != trajectory_id
            ):
                raise ValueError("formal gateway commitment differs from sealed transport pins")
            if evidence.signed_receipt is not None and (
                evidence.signed_receipt.receipt.request_commitment != commitment
            ):
                raise ValueError("formal signed receipt binds another request commitment")
            accepted = evidence.accepted_attestation
            if accepted is not None and (
                accepted.trusted_gateway_public_key_sha256
                != spec.gateway_trust_policy.trusted_gateway_public_key_sha256
                or accepted.trusted_gateway_build_sha256
                != spec.gateway_trust_policy.trusted_gateway_build_sha256
                or accepted.trusted_gateway_source_sha256
                != spec.gateway_trust_policy.trusted_gateway_source_sha256
            ):
                raise ValueError("formal gateway attestation differs from external trust pins")
        if len(self.budget_ledger.reservations) != len(self.call_evidence):
            raise ValueError("formal budget reservations do not cover every attempted call")
        if len(self.budget_ledger.settlements) != len(self.call_evidence):
            raise ValueError("formal budget settlements do not cover every attempted call")
        if self.budget_ledger.declared_charged_total.main_model_requests != len(self.call_evidence):
            raise ValueError("formal failed/successful call charging is incomplete")
        if self.budget_ledger.reservations != [item.reservation for item in self.call_evidence]:
            raise ValueError("formal budget ledger reservations differ from call evidence")
        if [item.evidence_receipt_hash for item in self.budget_ledger.settlements] != [
            item.evidence_hash for item in self.call_evidence
        ]:
            raise ValueError("formal budget settlements bind different call evidence")
        expected_outcomes = [
            (
                BudgetOutcome.SUCCEEDED
                if item.outcome is FormalLiveCallOutcome.PROVIDER_COMPLETION
                else BudgetOutcome.FAILED
            )
            for item in self.call_evidence
        ]
        if [item.outcome for item in self.budget_ledger.settlements] != expected_outcomes:
            raise ValueError("formal budget settlements hide failed gateway calls")
        verified_evidence = [
            item for item in self.call_evidence if item.accepted_attestation is not None
        ]
        if len(self.post_run_gateway_replays) != len(verified_evidence):
            raise ValueError("formal artifact omits a verified gateway signature replay")
        for evidence, replay in zip(
            verified_evidence,
            self.post_run_gateway_replays,
            strict=True,
        ):
            assert evidence.signed_receipt is not None
            assert evidence.accepted_attestation is not None
            if (
                replay.receipt_hash != evidence.signed_receipt.receipt.receipt_hash
                or replay.envelope_hash != evidence.signed_receipt.envelope_hash
                or replay.request_commitment_hash != evidence.request_commitment.commitment_hash
                or replay.accepted_attestation_hash
                != evidence.accepted_attestation.attestation_hash
                or replay.provider_completion_eligible != evidence.provider_completion_eligible
            ):
                raise ValueError("post-run replay belongs to another gateway exchange")
        runtime_completed = (
            self.final_snapshot.status is AdaptiveLoopRunStatus.PAUSED_BUDGET
            and len(self.final_snapshot.events) == _TURN_COUNT
            and len(self.call_evidence) == _TURN_COUNT
            and all(
                item.outcome is FormalLiveCallOutcome.PROVIDER_COMPLETION
                for item in self.call_evidence
            )
        )
        if runtime_completed:
            for event, evidence in zip(
                self.final_snapshot.events,
                self.call_evidence,
                strict=True,
            ):
                signed = evidence.signed_receipt
                if signed is None or not isinstance(
                    signed.receipt,
                    AdaptiveTransportGatewayReceipt,
                ):
                    raise ValueError("completed turn lacks a signed HTTP response receipt")
                receipt_projection = signed.receipt
                interaction = event.interaction
                if (
                    event.step_index != evidence.step_index
                    or interaction.model_call_registrations != [evidence.registration]
                    or interaction.messages != evidence.request_messages
                    or interaction.messages_sha256
                    != evidence.request_commitment.request_messages_sha256
                    or interaction.provider != spec.gateway_trust_policy.provider_name
                    or interaction.model_name != spec.gateway_trust_policy.model_name
                    or interaction.response_binding.payload_sha256
                    != receipt_projection.visible_output_utf8_sha256
                    or interaction.reasoning_binding.payload_sha256
                    != receipt_projection.reasoning_output_utf8_sha256
                    or receipt_projection.provider_response_model
                    != spec.gateway_trust_policy.model_name
                    or not receipt_projection.provider_response_model_matches_committed_model
                ):
                    raise ValueError("completed event differs from its signed gateway exchange")
        sovereign = spec.arm_runtime_plan.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        receipt = self.sovereign_recall_use_receipt
        if (receipt is not None) and not sovereign:
            raise ValueError("A1--A3 formal artifacts forbid sovereign recall-use receipts")
        if receipt is not None and (
            receipt.blinded_cell_id != spec.cell_binding.blinded_cell_id
            or receipt.scenario_id != spec.public_scenario.scenario_id
            or receipt.cell_binding_hash != spec.cell_binding.cell_binding_hash
            or receipt.arm_runtime_plan_hash != spec.arm_runtime_plan.plan_hash
            or receipt.final_snapshot_hash != self.final_snapshot.snapshot_hash
        ):
            raise ValueError("sovereign recall-use receipt belongs to another cell run")
        arm_gate = bool(
            self.arm_realization_audit and self.arm_realization_audit.capability_matrix_realized
        )
        recall_gate = not sovereign or bool(
            receipt and receipt.actual_sovereign_recall_use_verified
        )
        terminal_expected = runtime_completed and arm_gate and recall_gate
        if terminal_expected != (self.terminal is not None):
            raise ValueError("formal terminal presence disagrees with its arm/recall gates")
        if runtime_completed and len(self.post_run_gateway_replays) != _TURN_COUNT:
            raise ValueError("twelve-turn runtime lacks twelve gateway signature replays")
        if self.terminal is not None:
            terminal = self.terminal
            if self.arm_realization_audit is None:
                raise ValueError("formal terminal lacks an arm realization audit")
            if (
                self.audit_raw_final_manifest is None
                or self.controller_visible_final_manifest is None
            ):
                raise ValueError("formal terminal lacks final memory manifests")
            if len(self.post_run_gateway_replays) != _TURN_COUNT:
                raise ValueError("formal terminal lacks twelve post-run gateway replays")
            audit = self.arm_realization_audit
            assert audit is not None
            if (
                audit.parent_protocol_hash != spec.arm_runtime_plan.parent_protocol_hash
                or audit.arm is not spec.arm_runtime_plan.arm
                or audit.plan_hash != spec.arm_runtime_plan.plan_hash
                or audit.snapshot_hash != self.final_snapshot.snapshot_hash
            ):
                raise ValueError("formal arm audit belongs to another sealed trajectory")
            if (
                self.audit_raw_final_manifest.cell_binding_hash
                != spec.cell_binding.cell_binding_hash
                or self.controller_visible_final_manifest.cell_binding_hash
                != spec.cell_binding.cell_binding_hash
            ):
                raise ValueError("formal memory manifests belong to another cell")
            if (
                terminal.spec_hash != spec.spec_hash
                or terminal.snapshot_hash != self.final_snapshot.snapshot_hash
                or terminal.arm_audit_hash != audit.audit_hash
                or terminal.budget_ledger_hash != self.budget_ledger.ledger_hash
                or terminal.call_evidence_hashes
                != [item.evidence_hash for item in self.call_evidence]
                or terminal.post_run_gateway_replay_hashes
                != [item.replay_hash for item in self.post_run_gateway_replays]
            ):
                raise ValueError("formal terminal lineage differs from retained run evidence")
            if terminal.sovereign_recall_use_receipt_hash != (
                receipt.receipt_hash if receipt is not None else None
            ):
                raise ValueError("terminal binds the wrong sovereign recall-use receipt")
            if terminal.formal_eligible != self.formal_eligible:
                raise ValueError("artifact and terminal formal verdicts disagree")
        elif self.formal_eligible:
            raise ValueError("failed/incomplete formal cell cannot be eligible")
        expected_test = (
            spec.execution_track is FormalLiveExecutionTrack.ZERO_NETWORK_SIGNED_TEST_DOUBLE
        )
        if self.test_only_non_confirmatory != expected_test:
            raise ValueError("formal artifact test-only marker differs from its sealed track")
        if expected_test and self.formal_eligible:
            raise ValueError("zero-network signed test doubles are never confirmatory evidence")
        if (self.runtime_failure_sha256 is None) != (self.terminal is not None):
            raise ValueError("formal runtime failure marker disagrees with terminal gates")
        return self


class FormalBenchmarkCellRunArtifact(FormalBenchmarkCellRunArtifactContent):
    artifact_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> FormalBenchmarkCellRunArtifact:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise ValueError("formal benchmark cell artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> FormalBenchmarkCellRunArtifact:
        content = FormalBenchmarkCellRunArtifactContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, artifact_hash=canonical_sha256(payload))


class _GatewayCompletionFailure(RuntimeError):
    pass


class _DreamingOnlyEnvironment:
    """Expose the sole A4 intervention without any retrieval/network side path."""

    def __init__(self, delegate: AdaptiveResearchCapabilityEnvironment) -> None:
        self._delegate = delegate

    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset({ResearchOperator.CONSOLIDATE_DREAMING})

    def execute(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback:
        if proposal.operator is not ResearchOperator.CONSOLIDATE_DREAMING:
            raise AdaptiveLoopBenchmarkLiveRunError(
                "formal benchmark environment exposes only deterministic Dreaming"
            )
        return self._delegate.execute(seed=seed, snapshot=snapshot, proposal=proposal)


class _UnavailableFormalTemporaryDispatcher:
    """Expose the frozen capability but fail closed until signed worker fan-out exists."""

    def dispatch(
        self,
        *,
        tasks: Sequence[TemporaryResearchTask],
        **_: Any,
    ) -> TemporaryAgentBatchOutcome:
        del tasks
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal benchmark temporary-Agent fan-out has no signed gateway implementation"
        )


class _SignedGatewayCompletion:
    def __init__(
        self,
        *,
        spec: FormalBenchmarkCellRunSpec,
        attestation: ArmRuntimeAttestation,
        loop_output: Path,
        transport: SignedGatewayTransport,
        replay_ledger: TransportGatewayReplayLedger,
        clock: Callable[[], datetime],
        request_id_factory: Callable[[], str],
        nonce_factory: Callable[[], str],
        spec_path: Path,
        receipt_root: Path,
        bridge: AdaptiveLoopBenchmarkReceiptBridge,
    ) -> None:
        self.spec = spec
        self.attestation = attestation
        self.loop_output = loop_output
        self.transport = transport
        self.replay_ledger = replay_ledger
        self.clock = clock
        self.request_id_factory = request_id_factory
        self.nonce_factory = nonce_factory
        self.spec_path = spec_path
        self.receipt_root = receipt_root
        self.bridge = bridge
        self.reservations: list[BudgetReservation] = []
        self.evidence: list[FormalGatewayCallEvidence] = []
        self.walltimes_ms: list[int] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        call_index = len(self.reservations) + 1
        if call_index > _TURN_COUNT:
            raise _GatewayCompletionFailure("formal cell exceeded its twelve-call budget")
        _revalidate_before_provider_call(
            spec=self.spec,
            spec_path=self.spec_path,
            receipt_root=self.receipt_root,
            bridge=self.bridge,
            transport=self.transport,
        )
        messages = kwargs.get("messages")
        response_schema = kwargs.get("response_schema")
        if not isinstance(messages, list) or not isinstance(response_schema, dict):
            raise _GatewayCompletionFailure("formal completion lacks exact messages/schema")
        registration = _current_action_registration(
            loop_output=self.loop_output,
            messages=messages,
            response_schema=response_schema,
        )
        reservation = build_budget_reservation(
            attestation=self.attestation,
            reservation_id=f"formal-main-{call_index:02d}",
            operation_kind=BudgetOperationKind.MAIN_MODEL_REQUEST,
            maximum_wall_time_milliseconds=_MODEL_RESERVATION_MILLISECONDS,
        )
        request_bytes = _gateway_request_bytes(
            kwargs,
            provider_name=self.spec.gateway_trust_policy.provider_name,
            model_name=self.spec.gateway_trust_policy.model_name,
        )
        now = _utc_seconds(self.clock())
        commitment = build_transport_gateway_request_commitment(
            request_bytes=request_bytes,
            request_id=self.request_id_factory(),
            provider_name=self.spec.gateway_trust_policy.provider_name,
            model_name=self.spec.gateway_trust_policy.model_name,
            request_url=self.spec.gateway_trust_policy.request_url,
            allowlisted_origins=self.spec.gateway_trust_policy.allowlisted_origins,
            nonce=self.nonce_factory(),
            issued_at_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            cell_id=self.spec.cell_binding.blinded_cell_id,
            trajectory_id=self.attestation.trajectory_id,
            reservation_id=reservation.reservation_id,
            reservation_hash=reservation.reservation_hash,
            pre_call_id=registration.registration_id,
            pre_call_hash=registration.registration_hash,
            max_redirects=self.spec.gateway_trust_policy.max_redirects,
        )
        if commitment.request_messages_sha256 != registration.messages_sha256:
            raise _GatewayCompletionFailure(
                "gateway request messages differ from the loop call registration"
            )
        worker_request = build_adaptive_transport_gateway_worker_request(
            request_commitment=commitment,
            request_bytes=request_bytes,
        )
        pre_call_dir = self.loop_output / "formal-gateway" / f"call-{call_index:02d}"
        _write_contract_once(pre_call_dir / "budget-reservation.json", reservation)
        _write_contract_once(pre_call_dir / "request-commitment.json", commitment)
        _write_contract_once(pre_call_dir / "worker-request.json", worker_request)

        self.reservations.append(reservation)
        started = time.perf_counter_ns()
        output_sha256: str | None = None
        try:
            output_bytes = self.transport(canonical_json(worker_request).encode("utf-8"))
            output_sha256 = _sha256_bytes(output_bytes)
            worker_output = load_adaptive_transport_gateway_worker_output(output_bytes)
            signed = worker_output.signed_receipt
            accepted = verify_adaptive_transport_gateway_receipt(
                signed,
                expected_request_commitment=commitment,
                trusted_public_key_sha256=(
                    self.spec.gateway_trust_policy.trusted_gateway_public_key_sha256
                ),
                trusted_gateway_build_sha256=(
                    self.spec.gateway_trust_policy.trusted_gateway_build_sha256
                ),
                trusted_gateway_source_sha256=(
                    self.spec.gateway_trust_policy.trusted_gateway_source_sha256
                ),
                allowlisted_origins=self.spec.gateway_trust_policy.allowlisted_origins,
                now_utc=_utc_seconds(self.clock()),
                replay_ledger=self.replay_ledger,
            )
            _write_contract_once(pre_call_dir / "signed-worker-output.json", worker_output)
            _write_contract_once(pre_call_dir / "verified-attestation.json", accepted)
        except Exception as exc:  # noqa: BLE001 - failed call is charged evidence.
            elapsed_ms = _elapsed_ms(started)
            failure_hash = _failure_hash(exc)
            evidence = FormalGatewayCallEvidence.create(
                spec_hash=self.spec.spec_hash,
                call_index=call_index,
                step_index=registration.step_index,
                attempt_index=registration.attempt_index,
                registration=registration,
                reservation=reservation,
                request_messages=messages,
                request_messages_sha256=registration.messages_sha256,
                request_commitment=commitment,
                worker_request=worker_request,
                worker_request_hash=worker_request.worker_request_hash,
                gateway_worker_stdout_sha256=output_sha256,
                signed_receipt=None,
                accepted_attestation=None,
                completion_payload_hash=None,
                outcome=FormalLiveCallOutcome.UNVERIFIED_GATEWAY_FAILURE,
                operation_started=True,
                charged_even_when_failed=True,
                external_gateway_signature_verified=False,
                provider_completion_eligible=False,
                process_local_trace_used_for_formality=False,
                failure_sha256=failure_hash,
            )
            self.evidence.append(evidence)
            self.walltimes_ms.append(elapsed_ms)
            _write_contract_once(pre_call_dir / "call-evidence.json", evidence)
            raise _GatewayCompletionFailure(
                "formal signed gateway invocation or verification failed"
            ) from exc

        elapsed_ms = _elapsed_ms(started)
        completion = worker_output.completion
        if not accepted.provider_completion_eligible or completion is None:
            outcome = (
                FormalLiveCallOutcome.SIGNED_TRANSPORT_FAILURE
                if accepted.outcome == "transport_failure"
                else FormalLiveCallOutcome.SIGNED_HTTP_FAILURE
            )
            evidence = FormalGatewayCallEvidence.create(
                spec_hash=self.spec.spec_hash,
                call_index=call_index,
                step_index=registration.step_index,
                attempt_index=registration.attempt_index,
                registration=registration,
                reservation=reservation,
                request_messages=messages,
                request_messages_sha256=registration.messages_sha256,
                request_commitment=commitment,
                worker_request=worker_request,
                worker_request_hash=worker_request.worker_request_hash,
                gateway_worker_stdout_sha256=output_sha256,
                signed_receipt=signed,
                accepted_attestation=accepted,
                completion_payload_hash=None,
                outcome=outcome,
                operation_started=True,
                charged_even_when_failed=True,
                external_gateway_signature_verified=True,
                provider_completion_eligible=False,
                process_local_trace_used_for_formality=False,
                failure_sha256=canonical_sha256(
                    {"outcome": accepted.outcome, "receipt_hash": signed.receipt.receipt_hash}
                ),
            )
            self.evidence.append(evidence)
            self.walltimes_ms.append(elapsed_ms)
            _write_contract_once(pre_call_dir / "call-evidence.json", evidence)
            raise _GatewayCompletionFailure("signed gateway did not return a provider completion")

        try:
            if elapsed_ms > _MODEL_RESERVATION_MILLISECONDS:
                raise ValueError("formal gateway call exceeded its pre-call reservation")
            receipt = signed.receipt
            expected_model = self.spec.gateway_trust_policy.model_name
            expected_model_hash = _sha256_bytes(expected_model.encode("utf-8"))
            if (
                not isinstance(receipt, AdaptiveTransportGatewayReceipt)
                or completion.provider_response_model != expected_model
                or completion.provider_response_model_utf8_sha256 != expected_model_hash
                or receipt.provider_response_model != expected_model
                or receipt.provider_response_model_utf8_sha256 != expected_model_hash
                or not receipt.provider_response_model_matches_committed_model
            ):
                raise ValueError(
                    "signed provider response model differs from the committed Qwen model"
                )
            parsed = json.loads(completion.visible_output)
            if not isinstance(parsed, dict):
                raise TypeError("signed gateway completion top-level value is not an object")
        except (json.JSONDecodeError, TypeError) as exc:
            evidence = FormalGatewayCallEvidence.create(
                spec_hash=self.spec.spec_hash,
                call_index=call_index,
                step_index=registration.step_index,
                attempt_index=registration.attempt_index,
                registration=registration,
                reservation=reservation,
                request_messages=messages,
                request_messages_sha256=registration.messages_sha256,
                request_commitment=commitment,
                worker_request=worker_request,
                worker_request_hash=worker_request.worker_request_hash,
                gateway_worker_stdout_sha256=output_sha256,
                signed_receipt=signed,
                accepted_attestation=accepted,
                completion_payload_hash=completion.completion_payload_hash,
                outcome=FormalLiveCallOutcome.SIGNED_RESPONSE_VALIDATION_FAILURE,
                operation_started=True,
                charged_even_when_failed=True,
                external_gateway_signature_verified=True,
                provider_completion_eligible=True,
                process_local_trace_used_for_formality=False,
                failure_sha256=_failure_hash(exc),
            )
            self.evidence.append(evidence)
            self.walltimes_ms.append(elapsed_ms)
            _write_contract_once(pre_call_dir / "call-evidence.json", evidence)
            raise _GatewayCompletionFailure(
                "signed gateway completion failed response validation"
            ) from exc
        evidence = FormalGatewayCallEvidence.create(
            spec_hash=self.spec.spec_hash,
            call_index=call_index,
            step_index=registration.step_index,
            attempt_index=registration.attempt_index,
            registration=registration,
            reservation=reservation,
            request_messages=messages,
            request_messages_sha256=registration.messages_sha256,
            request_commitment=commitment,
            worker_request=worker_request,
            worker_request_hash=worker_request.worker_request_hash,
            gateway_worker_stdout_sha256=output_sha256,
            signed_receipt=signed,
            accepted_attestation=accepted,
            completion_payload_hash=completion.completion_payload_hash,
            outcome=FormalLiveCallOutcome.PROVIDER_COMPLETION,
            operation_started=True,
            charged_even_when_failed=True,
            external_gateway_signature_verified=True,
            provider_completion_eligible=True,
            process_local_trace_used_for_formality=False,
            failure_sha256=None,
        )
        self.evidence.append(evidence)
        self.walltimes_ms.append(elapsed_ms)
        _write_contract_once(pre_call_dir / "call-evidence.json", evidence)
        return LLMJsonCompletionResult(
            provider=self.spec.gateway_trust_policy.provider_name,
            base_url=self.spec.gateway_trust_policy.request_url.rsplit("/", 2)[0],
            model_name=self.spec.gateway_trust_policy.model_name,
            endpoint=self.spec.gateway_trust_policy.request_url,
            response_text=completion.visible_output,
            parsed_json=parsed,
            usage=completion.usage,
            temperature=float(kwargs.get("temperature", 0.0)),
            reasoning_text=completion.reasoning_output,
            reasoning_transport=reasoning_transport_for_provider(
                self.spec.gateway_trust_policy.provider_name
            ),
            transport_trace=None,
        )


def build_formal_gateway_trust_policy(
    *,
    model_name: str,
    request_url: str,
    allowlisted_origins: Collection[str],
    trusted_gateway_public_key_sha256: str,
    trusted_gateway_build_sha256: str,
    trusted_gateway_source_sha256: str,
    max_redirects: int = 0,
) -> FormalGatewayTrustPolicy:
    return FormalGatewayTrustPolicy.create(
        model_name=model_name,
        request_url=request_url,
        allowlisted_origins=tuple(sorted(set(allowlisted_origins))),
        trusted_gateway_public_key_sha256=trusted_gateway_public_key_sha256,
        trusted_gateway_build_sha256=trusted_gateway_build_sha256,
        trusted_gateway_source_sha256=trusted_gateway_source_sha256,
        max_redirects=max_redirects,
    )


def build_formal_benchmark_cell_run_spec(
    *,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    public_scenario: AdaptiveLoopBenchmarkPublicScenario,
    blinded_cell: AdaptiveLoopBenchmarkBlindedCell,
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    arm_runtime_plan: BenchmarkArmRuntimePlan,
    seed: AdaptiveResearchSeed,
    policy: AdaptiveLoopPolicy,
    gateway_trust_policy: FormalGatewayTrustPolicy,
    execution_track: FormalLiveExecutionTrack,
) -> FormalBenchmarkCellRunSpec:
    """Canonicalize every public/trust input before a provider can be reached."""

    checked_bridge = AdaptiveLoopBenchmarkReceiptBridge.model_validate(
        bridge.model_dump(mode="json")
    )
    checked_scenario = AdaptiveLoopBenchmarkPublicScenario.model_validate(
        public_scenario.model_dump(mode="json")
    )
    checked_cell = AdaptiveLoopBenchmarkBlindedCell.model_validate(
        blinded_cell.model_dump(mode="json")
    )
    checked_binding = AdaptiveLoopBenchmarkCellExecutionBinding.model_validate(
        cell_binding.model_dump(mode="json")
    )
    checked_plan = BenchmarkArmRuntimePlan.model_validate(arm_runtime_plan.model_dump(mode="json"))
    checked_seed = AdaptiveResearchSeed.model_validate(seed.model_dump(mode="json"))
    checked_policy = AdaptiveLoopPolicy.model_validate(policy.model_dump(mode="json"))
    checked_trust = FormalGatewayTrustPolicy.model_validate(
        gateway_trust_policy.model_dump(mode="json")
    )
    if checked_bridge.cell(checked_binding.blinded_cell_id) != checked_binding:
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal cell binding is not the exact sealed bridge leaf"
        )
    if (
        next(
            (
                item
                for item in checked_bridge.blinded_manifest.cells
                if item.blinded_cell_id == checked_cell.blinded_cell_id
            ),
            None,
        )
        != checked_cell
    ):
        raise AdaptiveLoopBenchmarkLiveRunError("formal blinded cell differs from bridge")
    if (
        next(
            (
                item
                for item in checked_bridge.execution_protocol.public_scenarios
                if item.scenario_id == checked_scenario.scenario_id
            ),
            None,
        )
        != checked_scenario
    ):
        raise AdaptiveLoopBenchmarkLiveRunError("formal public scenario differs from bridge")
    source_hashes = _source_module_hashes()
    raw_plane_id, controller_plane_id = _plane_ids(checked_binding)
    raw_manifest, controller_manifest = _initial_plane_manifest_bytes(
        binding=checked_binding,
        plan=checked_plan,
        seed=checked_seed,
        policy=checked_policy,
        trust_policy=checked_trust,
        source_hashes=source_hashes,
        raw_plane_id=raw_plane_id,
        controller_plane_id=controller_plane_id,
    )
    return FormalBenchmarkCellRunSpec.create(
        execution_track=execution_track,
        receipt_bridge_hash=checked_bridge.receipt_bridge_hash,
        public_scenario=checked_scenario,
        blinded_cell=checked_cell,
        cell_binding=checked_binding,
        arm_runtime_plan=checked_plan,
        seed=checked_seed,
        policy=checked_policy,
        seed_sha256=canonical_sha256(checked_seed),
        policy_sha256=canonical_sha256(checked_policy),
        gateway_trust_policy=checked_trust,
        initial_audit_raw_plane_id=raw_plane_id,
        initial_controller_visible_plane_id=controller_plane_id,
        initial_audit_raw_plane_manifest_sha256=_sha256_bytes(raw_manifest),
        initial_controller_visible_plane_manifest_sha256=_sha256_bytes(controller_manifest),
        budget_limit=BudgetVector(
            main_model_requests=_TURN_COUNT,
            wall_time_milliseconds=_TURN_COUNT * _MODEL_RESERVATION_MILLISECONDS,
        ),
        source_module_sha256s=source_hashes,
    )


def run_formal_benchmark_cell(
    *,
    receipt_root: Path | str,
    output_dir: Path | str,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    public_scenario: AdaptiveLoopBenchmarkPublicScenario,
    blinded_cell: AdaptiveLoopBenchmarkBlindedCell,
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    arm_runtime_plan: BenchmarkArmRuntimePlan,
    seed: AdaptiveResearchSeed,
    policy: AdaptiveLoopPolicy,
    gateway_trust_policy: FormalGatewayTrustPolicy,
    raw_memory_store: RawMemoryStore,
    gateway_transport: SignedGatewayTransport,
    replay_ledger: TransportGatewayReplayLedger,
    clock: Callable[[], datetime] | None = None,
    request_id_factory: Callable[[], str] | None = None,
    nonce_factory: Callable[[], str] | None = None,
) -> FormalBenchmarkCellRunArtifact:
    """Run one signed live cell; retain failures without scoring the answer."""

    root = Path(receipt_root).resolve()
    output_root = Path(output_dir).resolve()
    disk_bridge = load_adaptive_loop_benchmark_receipt_bridge(root)
    if disk_bridge != bridge:
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal runner bridge differs from the sealed disk bridge"
        )
    test_only = getattr(gateway_transport, "test_only", None)
    if not isinstance(test_only, bool):
        raise AdaptiveLoopBenchmarkLiveRunError(
            "gateway transport must explicitly declare whether it is a test double"
        )
    execution_track = (
        FormalLiveExecutionTrack.ZERO_NETWORK_SIGNED_TEST_DOUBLE
        if test_only
        else FormalLiveExecutionTrack.EXTERNAL_SIGNED_GATEWAY
    )
    spec = build_formal_benchmark_cell_run_spec(
        bridge=bridge,
        public_scenario=public_scenario,
        blinded_cell=blinded_cell,
        cell_binding=cell_binding,
        arm_runtime_plan=arm_runtime_plan,
        seed=seed,
        policy=policy,
        gateway_trust_policy=gateway_trust_policy,
        execution_track=execution_track,
    )
    _require_fresh_output_root(output_root)
    spec_path = output_root / _SPEC_FILENAME
    _write_contract_once(spec_path, spec)
    now = clock or (lambda: datetime.now(timezone.utc))

    raw_plane, controller_plane = _initial_plane_manifest_bytes(
        binding=spec.cell_binding,
        plan=spec.arm_runtime_plan,
        seed=spec.seed,
        policy=spec.policy,
        trust_policy=spec.gateway_trust_policy,
        source_hashes=spec.source_module_sha256s,
        raw_plane_id=spec.initial_audit_raw_plane_id,
        controller_plane_id=spec.initial_controller_visible_plane_id,
    )
    attestation = build_arm_runtime_attestation(
        bridge=bridge,
        blinded_cell_id=spec.cell_binding.blinded_cell_id,
        audit_raw_memory_plane_id=spec.initial_audit_raw_plane_id,
        controller_visible_memory_plane_id=spec.initial_controller_visible_plane_id,
        audit_raw_manifest=raw_plane,
        controller_visible_manifest=controller_plane,
    )
    loop_output = output_root / "loop"
    recorder = _SignedGatewayCompletion(
        spec=spec,
        attestation=attestation,
        loop_output=loop_output,
        transport=gateway_transport,
        replay_ledger=replay_ledger,
        clock=now,
        request_id_factory=request_id_factory or (lambda: f"ar-{uuid.uuid4().hex}"),
        nonce_factory=nonce_factory or (lambda: secrets.token_hex(16)),
        spec_path=spec_path,
        receipt_root=root,
        bridge=bridge,
    )
    context_adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=spec.public_scenario,
        blinded_cell=spec.blinded_cell,
        raw_memory_store=raw_memory_store,
    )
    arm_adapter = build_benchmark_arm_adapter(spec.arm_runtime_plan.arm)
    if arm_adapter.plan != spec.arm_runtime_plan:
        raise AdaptiveLoopBenchmarkLiveRunError("formal arm adapter differs from sealed plan")
    capability_delegate = AdaptiveResearchCapabilityEnvironment(
        output_dir=loop_output,
        raw_memory_store=raw_memory_store,
        literature_clients={"disabled": _NoLiteratureClient()},
        clock=now,
    )
    environment = _DreamingOnlyEnvironment(capability_delegate)
    runtime_error: BaseException | None = None
    try:
        final_snapshot = run_adaptive_research_loop(
            seed=spec.seed,
            policy=spec.policy,
            raw_memory_store=raw_memory_store,
            output_dir=loop_output,
            environment=environment,
            operator_catalog_provider=arm_adapter,
            external_turn_context_provider=context_adapter,
            temporary_dispatcher=_UnavailableFormalTemporaryDispatcher(),
            completion=recorder,
            clock=now,
        )
    except Exception as exc:  # noqa: BLE001 - scientific failures remain data.
        runtime_error = exc
        final_snapshot = _load_latest_snapshot(loop_output, raw_memory_store)
        if not recorder.reservations and not recorder.evidence:
            raise AdaptiveLoopBenchmarkLiveRunError(
                "formal cell failed before any signed-gateway operation started"
            ) from exc
        if len(recorder.reservations) != len(recorder.evidence):
            raise AdaptiveLoopBenchmarkLiveRunError(
                "formal gateway attempt lacks balanced reservation/evidence state"
            ) from exc

    ledger = _build_call_budget_ledger(attestation=attestation, recorder=recorder)
    post_run_replays = _post_run_gateway_replays(
        recorder=recorder,
        trust_policy=spec.gateway_trust_policy,
        replay_ledger=replay_ledger,
    )
    completed = (
        runtime_error is None
        and final_snapshot.status is AdaptiveLoopRunStatus.PAUSED_BUDGET
        and len(final_snapshot.events) == _TURN_COUNT
        and len(recorder.evidence) == _TURN_COUNT
        and all(
            item.outcome is FormalLiveCallOutcome.PROVIDER_COMPLETION for item in recorder.evidence
        )
    )
    arm_audit: BenchmarkArmRealizationAudit | None = None
    raw_manifest: FormalCellEvidenceManifest | None = None
    controller_manifest: FormalCellEvidenceManifest | None = None
    recall_receipt: SovereignRecallUseReceipt | None = None
    terminal: FormalBenchmarkCellTerminal | None = None
    if completed:
        arm_audit = audit_benchmark_arm_realization(
            plan=spec.arm_runtime_plan,
            snapshot=final_snapshot,
            artifact_root=loop_output,
        )
        if not arm_audit.capability_matrix_realized:
            runtime_error = AdaptiveLoopBenchmarkLiveRunError(
                "formal trajectory failed arm realization audit"
            )
            completed = False
        else:
            raw_manifest = _build_raw_final_manifest(
                binding=spec.cell_binding,
                snapshot=final_snapshot,
                raw_memory_store=raw_memory_store,
            )
            controller_manifest = _build_controller_final_manifest(
                binding=spec.cell_binding,
                snapshot=final_snapshot,
            )
            actual_use_verified = False
            recall_receipt_hash: str | None = None
            if spec.arm_runtime_plan.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN:
                try:
                    recall_receipt = audit_sovereign_recall_use(
                        _snapshot_path(loop_output, final_snapshot),
                        public_scenario=spec.public_scenario,
                        blinded_cell=spec.blinded_cell,
                        cell_binding=spec.cell_binding,
                        arm_runtime_plan=spec.arm_runtime_plan,
                        raw_memory_store=raw_memory_store,
                        verified_gateway_exchanges=_sovereign_gateway_exchanges(recorder.evidence),
                        gateway_verification_policy=(
                            SovereignRecallGatewayVerificationPolicy(
                                trusted_public_key_sha256=(
                                    spec.gateway_trust_policy.trusted_gateway_public_key_sha256
                                ),
                                trusted_gateway_build_sha256=(
                                    spec.gateway_trust_policy.trusted_gateway_build_sha256
                                ),
                                trusted_gateway_source_sha256=(
                                    spec.gateway_trust_policy.trusted_gateway_source_sha256
                                ),
                                allowlisted_origins=(spec.gateway_trust_policy.allowlisted_origins),
                                replay_ledger=replay_ledger,
                            )
                        ),
                        output_path=(output_root / "sovereign-recall-use-receipt-v1.json"),
                    )
                except SovereignRecallUseAuditError as exc:
                    runtime_error = exc
                    completed = False
                else:
                    recall_receipt_hash = recall_receipt.receipt_hash
                    actual_use_verified = recall_receipt.actual_sovereign_recall_use_verified
                    if not actual_use_verified:
                        runtime_error = AdaptiveLoopBenchmarkLiveRunError(
                            "A4 terminal blocked: sovereign recall was not observably used"
                        )
                        completed = False
            if completed:
                terminal = FormalBenchmarkCellTerminal.create(
                    spec_hash=spec.spec_hash,
                    snapshot_hash=final_snapshot.snapshot_hash,
                    arm_audit_hash=arm_audit.audit_hash,
                    budget_ledger_hash=ledger.ledger_hash,
                    call_evidence_hashes=[item.evidence_hash for item in recorder.evidence],
                    post_run_gateway_replay_hashes=[item.replay_hash for item in post_run_replays],
                    sovereign_recall_use_receipt_hash=recall_receipt_hash,
                    actual_sovereign_recall_use_verified=actual_use_verified,
                    arm=spec.arm_runtime_plan.arm,
                    execution_track=spec.execution_track,
                    formal_eligible=(
                        spec.execution_track is FormalLiveExecutionTrack.EXTERNAL_SIGNED_GATEWAY
                    ),
                )
    if not completed:
        terminal = None
    failure_hash = (
        None
        if completed
        else _failure_hash(
            runtime_error or AdaptiveLoopBenchmarkLiveRunError("formal cell did not complete")
        )
    )
    artifact = FormalBenchmarkCellRunArtifact.create(
        run_spec=spec,
        final_snapshot=final_snapshot,
        call_evidence=recorder.evidence,
        budget_ledger=ledger,
        post_run_gateway_replays=post_run_replays,
        arm_realization_audit=arm_audit,
        audit_raw_final_manifest=raw_manifest,
        controller_visible_final_manifest=controller_manifest,
        sovereign_recall_use_receipt=recall_receipt,
        terminal=terminal,
        runtime_failure_sha256=failure_hash,
        formal_eligible=bool(terminal and terminal.formal_eligible),
        test_only_non_confirmatory=(
            spec.execution_track is FormalLiveExecutionTrack.ZERO_NETWORK_SIGNED_TEST_DOUBLE
        ),
    )
    _write_contract_once(output_root / _ARTIFACT_FILENAME, artifact)
    return artifact


class _NoLiteratureClient:
    def search(self, *_: Any, **__: Any) -> list[Any]:
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal memory benchmark does not permit uncontrolled live literature retrieval"
        )


def load_formal_benchmark_cell_run_artifact(
    path: Path | str,
    *,
    expected_gateway_trust_policy: FormalGatewayTrustPolicy | None = None,
    replay_ledger: TransportGatewayReplayLedger | None = None,
) -> FormalBenchmarkCellRunArtifact:
    """Load one artifact and replay external signatures for any formal track.

    The embedded policy is content addressed but is not a trust root.  External
    runs therefore require the caller to supply the out-of-band pinned policy and
    the local anti-replay ledger populated by immediate verification.
    """

    payload = Path(path).resolve().read_bytes()
    try:
        artifact = FormalBenchmarkCellRunArtifact.model_validate_json(payload)
    except ValueError as exc:
        raise AdaptiveLoopBenchmarkLiveRunError(
            f"formal benchmark artifact is invalid: {exc}"
        ) from exc
    if payload != (canonical_json(artifact) + "\n").encode("utf-8"):
        raise AdaptiveLoopBenchmarkLiveRunError("formal benchmark artifact is not canonical JSON")
    external = artifact.run_spec.execution_track is FormalLiveExecutionTrack.EXTERNAL_SIGNED_GATEWAY
    if external and (expected_gateway_trust_policy is None or replay_ledger is None):
        raise AdaptiveLoopBenchmarkLiveRunError(
            "external formal artifact needs out-of-band gateway pins and anti-replay ledger"
        )
    if expected_gateway_trust_policy is not None:
        if expected_gateway_trust_policy != artifact.run_spec.gateway_trust_policy:
            raise AdaptiveLoopBenchmarkLiveRunError(
                "embedded gateway policy differs from the out-of-band trust policy"
            )
        if replay_ledger is None:
            raise AdaptiveLoopBenchmarkLiveRunError(
                "gateway signature replay needs the original local anti-replay ledger"
            )
        replayed = _replay_artifact_gateway_evidence(
            artifact=artifact,
            trust_policy=expected_gateway_trust_policy,
            replay_ledger=replay_ledger,
        )
        if replayed != artifact.post_run_gateway_replays:
            raise AdaptiveLoopBenchmarkLiveRunError(
                "stored post-run gateway replays differ from fresh signature replay"
            )
    return artifact


def _replay_artifact_gateway_evidence(
    *,
    artifact: FormalBenchmarkCellRunArtifact,
    trust_policy: FormalGatewayTrustPolicy,
    replay_ledger: TransportGatewayReplayLedger,
) -> list[PostRunAdaptiveTransportGatewayReplay]:
    replays: list[PostRunAdaptiveTransportGatewayReplay] = []
    for evidence in artifact.call_evidence:
        if evidence.signed_receipt is None or evidence.accepted_attestation is None:
            continue
        replays.append(
            replay_verify_adaptive_transport_gateway_attestation(
                evidence.signed_receipt,
                expected_request_commitment=evidence.request_commitment,
                accepted_attestation=evidence.accepted_attestation,
                trusted_public_key_sha256=trust_policy.trusted_gateway_public_key_sha256,
                trusted_gateway_build_sha256=trust_policy.trusted_gateway_build_sha256,
                trusted_gateway_source_sha256=trust_policy.trusted_gateway_source_sha256,
                allowlisted_origins=trust_policy.allowlisted_origins,
                replay_ledger=replay_ledger,
            )
        )
    return replays


def _gateway_request_bytes(
    kwargs: Mapping[str, Any],
    *,
    provider_name: str,
    model_name: str,
) -> bytes:
    messages = kwargs.get("messages")
    schema = kwargs.get("response_schema")
    schema_name = kwargs.get("response_schema_name")
    if not isinstance(messages, list) or not isinstance(schema, dict):
        raise AdaptiveLoopBenchmarkLiveRunError("formal gateway request lacks messages/schema")
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": kwargs.get("temperature", 0.0),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
    }
    max_tokens = kwargs.get("max_tokens")
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    thinking_mode = kwargs.get("thinking_mode")
    if thinking_mode == "enabled":
        payload["enable_thinking"] = True
        payload["thinking_budget"] = kwargs.get("thinking_budget") or 4_000
    elif thinking_mode == "disabled":
        payload["enable_thinking"] = False
    if reasoning_transport_for_provider(provider_name) != "dashscope_enable_thinking":
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal benchmark currently supports only the verified Qwen reasoning dialect"
        )
    return canonical_json(payload).encode("utf-8")


def _current_action_registration(
    *,
    loop_output: Path,
    messages: list[dict[str, str]],
    response_schema: dict[str, Any],
) -> AdaptiveActionModelCallRegistration:
    try:
        task = json.loads(messages[-1]["content"])
        step = int(task["step_index"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal action messages lack a current step"
        ) from exc
    directory = loop_output / "action-call-registrations" / f"step-{step:04d}"
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal action call has no immutable loop registration"
        )
    path = paths[-1]
    payload = path.read_bytes()
    registration = AdaptiveActionModelCallRegistration.model_validate_json(payload)
    if payload != (canonical_json(registration) + "\n").encode("utf-8"):
        raise AdaptiveLoopBenchmarkLiveRunError("formal action registration is not canonical")
    if registration.messages_sha256 != canonical_sha256(messages):
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal action registration differs from exact messages"
        )
    if registration.response_schema_sha256 != canonical_sha256(response_schema):
        raise AdaptiveLoopBenchmarkLiveRunError(
            "formal action registration differs from dynamic provider schema"
        )
    return registration


def _revalidate_before_provider_call(
    *,
    spec: FormalBenchmarkCellRunSpec,
    spec_path: Path,
    receipt_root: Path,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    transport: SignedGatewayTransport,
) -> None:
    if spec_path.read_bytes() != (canonical_json(spec) + "\n").encode("utf-8"):
        raise AdaptiveLoopBenchmarkLiveRunError("formal run spec changed before provider call")
    if load_adaptive_loop_benchmark_receipt_bridge(receipt_root) != bridge:
        raise AdaptiveLoopBenchmarkLiveRunError("sealed bridge changed before provider call")
    if _source_module_hashes() != spec.source_module_sha256s:
        raise AdaptiveLoopBenchmarkLiveRunError("formal runner source set changed mid-cell")
    expected_test = spec.execution_track is FormalLiveExecutionTrack.ZERO_NETWORK_SIGNED_TEST_DOUBLE
    if getattr(transport, "test_only", None) is not expected_test:
        raise AdaptiveLoopBenchmarkLiveRunError("gateway transport class changed mid-cell")


def _build_call_budget_ledger(
    *,
    attestation: ArmRuntimeAttestation,
    recorder: _SignedGatewayCompletion,
) -> BudgetLedger:
    settlements: list[BudgetLedgerEntry] = []
    for sequence, (reservation, evidence, elapsed_ms) in enumerate(
        zip(recorder.reservations, recorder.evidence, recorder.walltimes_ms, strict=True),
        start=1,
    ):
        outcome = (
            BudgetOutcome.SUCCEEDED
            if evidence.outcome is FormalLiveCallOutcome.PROVIDER_COMPLETION
            else BudgetOutcome.FAILED
        )
        settlements.append(
            build_budget_ledger_entry(
                reservation=reservation,
                sequence=sequence,
                outcome=outcome,
                actual_wall_time_milliseconds=elapsed_ms,
                evidence_receipt_hash=evidence.evidence_hash,
            )
        )
    return build_budget_ledger(
        attestation=attestation,
        budget_limit=BudgetVector(
            main_model_requests=_TURN_COUNT,
            wall_time_milliseconds=_TURN_COUNT * _MODEL_RESERVATION_MILLISECONDS,
        ),
        reservations=recorder.reservations,
        settlements=settlements,
    )


def _post_run_gateway_replays(
    *,
    recorder: _SignedGatewayCompletion,
    trust_policy: FormalGatewayTrustPolicy,
    replay_ledger: TransportGatewayReplayLedger,
) -> list[PostRunAdaptiveTransportGatewayReplay]:
    replays: list[PostRunAdaptiveTransportGatewayReplay] = []
    for evidence in recorder.evidence:
        if evidence.signed_receipt is None or evidence.accepted_attestation is None:
            continue
        replays.append(
            replay_verify_adaptive_transport_gateway_attestation(
                evidence.signed_receipt,
                expected_request_commitment=evidence.request_commitment,
                accepted_attestation=evidence.accepted_attestation,
                trusted_public_key_sha256=trust_policy.trusted_gateway_public_key_sha256,
                trusted_gateway_build_sha256=trust_policy.trusted_gateway_build_sha256,
                trusted_gateway_source_sha256=trust_policy.trusted_gateway_source_sha256,
                allowlisted_origins=trust_policy.allowlisted_origins,
                replay_ledger=replay_ledger,
            )
        )
    return replays


def _sovereign_gateway_exchanges(
    evidence_items: Sequence[FormalGatewayCallEvidence],
) -> list[SovereignRecallVerifiedGatewayExchange]:
    if len(evidence_items) != _TURN_COUNT:
        raise AdaptiveLoopBenchmarkLiveRunError(
            "A4 recall-use audit requires twelve signed action exchanges"
        )
    exchanges: list[SovereignRecallVerifiedGatewayExchange] = []
    for evidence in evidence_items:
        if (
            evidence.outcome is not FormalLiveCallOutcome.PROVIDER_COMPLETION
            or evidence.signed_receipt is None
            or evidence.accepted_attestation is None
        ):
            raise AdaptiveLoopBenchmarkLiveRunError(
                "A4 recall-use audit rejects any unsigned or failed action exchange"
            )
        exchanges.append(
            SovereignRecallVerifiedGatewayExchange.create(
                signed_receipt=evidence.signed_receipt,
                verified_attestation=evidence.accepted_attestation,
            )
        )
    return exchanges


def _snapshot_path(
    loop_output: Path,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> Path:
    path = (
        loop_output / "snapshots" / f"step-{len(snapshot.events):04d}-{snapshot.snapshot_hash}.json"
    )
    if not path.is_file():
        raise AdaptiveLoopBenchmarkLiveRunError("formal terminal snapshot file is missing")
    return path.resolve()


def _load_latest_snapshot(
    loop_output: Path,
    raw_memory_store: RawMemoryStore,
) -> AdaptiveResearchLoopSnapshot:
    paths = sorted((loop_output / "snapshots").glob("*.json"))
    if not paths:
        raise AdaptiveLoopBenchmarkLiveRunError("formal failed cell retained no snapshot")
    return load_adaptive_research_loop_snapshot(paths[-1], raw_memory_store=raw_memory_store)


def _build_raw_final_manifest(
    *,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    snapshot: AdaptiveResearchLoopSnapshot,
    raw_memory_store: RawMemoryStore,
) -> FormalCellEvidenceManifest:
    prefix = f"adaptive-loop:{snapshot.seed.loop_id}:"
    record_root = raw_memory_store.private_root / "projects" / snapshot.seed.project_id / "records"
    entries: list[FormalCellManifestEntry] = []
    for path in sorted(record_root.glob("*/*/*.json")):
        capture = raw_memory_store.load_record(
            path.resolve().relative_to(raw_memory_store.vault_root),
            project_id=snapshot.seed.project_id,
        )
        if capture.record.envelope.source_ref.startswith(prefix):
            raw_memory_store.verify_capture(capture)
            entries.append(
                FormalCellManifestEntry(
                    entry_id=capture.record.envelope.source_ref,
                    content_sha256=capture.record.record_hash,
                )
            )
    if not entries:
        raise AdaptiveLoopBenchmarkLiveRunError("formal raw-memory manifest is empty")
    return FormalCellEvidenceManifest.create(
        plane="audit_raw",
        cell_binding_hash=binding.cell_binding_hash,
        entries=entries,
        entry_count=len(entries),
    )


def _build_controller_final_manifest(
    *,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> FormalCellEvidenceManifest:
    entries = [
        FormalCellManifestEntry(
            entry_id="controller:snapshot:terminal",
            content_sha256=snapshot.snapshot_hash,
        )
    ]
    for event in snapshot.events:
        prefix = f"controller:step:{event.step_index}"
        entries.extend(
            [
                FormalCellManifestEntry(
                    entry_id=f"{prefix}:event",
                    content_sha256=event.event_hash,
                ),
                FormalCellManifestEntry(
                    entry_id=f"{prefix}:interaction",
                    content_sha256=event.interaction.interaction_hash,
                ),
                FormalCellManifestEntry(
                    entry_id=f"{prefix}:messages",
                    content_sha256=event.interaction.messages_sha256,
                ),
            ]
        )
    return FormalCellEvidenceManifest.create(
        plane="controller_visible",
        cell_binding_hash=binding.cell_binding_hash,
        entries=entries,
        entry_count=len(entries),
    )


def _source_module_hashes() -> dict[str, str]:
    paths: dict[str, Path] = {}
    for name, module in _SOURCE_MODULES.items():
        if module is None:
            paths[name] = Path(__file__).resolve()
            continue
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise AdaptiveLoopBenchmarkLiveRunError(f"source module {name!r} has no file")
        paths[name] = Path(module_file).resolve()
    return {name: _sha256_bytes(path.read_bytes()) for name, path in sorted(paths.items())}


def _plane_ids(binding: AdaptiveLoopBenchmarkCellExecutionBinding) -> tuple[str, str]:
    suffix = binding.cell_binding_hash[:24]
    return f"formal-audit-raw-{suffix}", f"formal-controller-{suffix}"


def _initial_plane_manifest_bytes(
    *,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    plan: BenchmarkArmRuntimePlan,
    seed: AdaptiveResearchSeed,
    policy: AdaptiveLoopPolicy,
    trust_policy: FormalGatewayTrustPolicy,
    source_hashes: Mapping[str, str],
    raw_plane_id: str,
    controller_plane_id: str,
) -> tuple[bytes, bytes]:
    common = {
        "cell_binding_hash": binding.cell_binding_hash,
        "plan_hash": plan.plan_hash,
        "seed_sha256": canonical_sha256(seed),
        "policy_sha256": canonical_sha256(policy),
        "gateway_trust_policy_hash": trust_policy.policy_hash,
        "source_module_sha256s": dict(source_hashes),
    }
    raw = canonical_json(
        {
            "schema_version": "formal-initial-audit-raw-plane-v1",
            "plane_id": raw_plane_id,
            "append_only": True,
            "controller_mutation_allowed": False,
            **common,
        }
    ).encode("utf-8")
    controller = canonical_json(
        {
            "schema_version": "formal-initial-controller-plane-v1",
            "plane_id": controller_plane_id,
            "derived_and_rebuildable": True,
            "audit_raw_mutation_allowed": False,
            **common,
        }
    ).encode("utf-8")
    return raw, controller


def _require_fresh_output_root(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise AdaptiveLoopBenchmarkLiveRunError("formal cell output directory is not fresh")
    path.mkdir(parents=True, exist_ok=True)


def _write_contract_once(path: Path, contract: KernelContract) -> None:
    payload = (canonical_json(contract) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveLoopBenchmarkLiveRunError(
                f"write-once formal artifact conflict: {path.name}"
            ) from None


def _utc_seconds(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AdaptiveLoopBenchmarkLiveRunError("formal gateway clock must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _elapsed_ms(started_ns: int) -> int:
    return max(1, math.ceil((time.perf_counter_ns() - started_ns) / 1_000_000))


def _failure_hash(exc: BaseException) -> str:
    return canonical_sha256(
        {"error_type": type(exc).__name__, "error_message_sha256": _sha256_bytes(str(exc).encode())}
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "AdaptiveLoopBenchmarkLiveRunError",
    "FormalBenchmarkCellRunArtifact",
    "FormalBenchmarkCellRunSpec",
    "FormalGatewayCallEvidence",
    "FormalGatewayTrustPolicy",
    "FormalLiveExecutionTrack",
    "SignedGatewayTransport",
    "build_formal_benchmark_cell_run_spec",
    "build_formal_gateway_trust_policy",
    "load_formal_benchmark_cell_run_artifact",
    "run_formal_benchmark_cell",
]
