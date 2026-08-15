"""One-cell, result-blind diagnostic runner for benchmark protocol v3.

This module composes the public-context adapter, the generic adaptive loop,
the four-arm operator adapter, and the immutable receipt layer.  It is a
diagnostic harness only: it accepts an injected local completion double, never
loads private scoring data, never scores an answer, and can never make a cell
formally eligible.  A live-provider gateway needs an independently anchored
transport implementation and intentionally remains outside this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
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
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research import (
    adaptive_loop_benchmark_arm_adapters as arm_adapter_module,
)
from autoresearch.research import adaptive_loop_benchmark_context as context_module
from autoresearch.research import adaptive_loop_benchmark_receipts as receipt_module
from autoresearch.research import adaptive_sovereign_loop as loop_module
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
    BudgetLedgerEntry,
    BudgetOperationKind,
    BudgetOutcome,
    BudgetReservation,
    BudgetVector,
    CellJournalEntry,
    CellJournalEventKind,
    CellJournalReplay,
    CellRuntimeEvidenceBundle,
    MechanicalChallengeTransitionReceipt,
    ProviderAttemptReceipt,
    ProviderAttemptStatus,
    ProviderExecutionMode,
    ProviderPreCallAnchor,
    TerminalEnvelope,
    build_arm_runtime_attestation,
    build_budget_ledger,
    build_budget_ledger_entry,
    build_budget_reservation,
    build_cell_journal_entry,
    build_cell_runtime_evidence_bundle,
    build_mechanical_transition_receipt,
    build_provider_attempt_receipt,
    build_provider_pre_call_anchor,
    build_terminal_envelope,
    load_adaptive_loop_benchmark_receipt_bridge,
    replay_cell_journal,
    write_cell_journal_entry_once,
    write_cell_runtime_evidence_once,
    write_terminal_envelope_once,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveLoopRunStatus,
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    ResearchOperator,
    TemporaryAgentBatchOutcome,
    TemporaryResearchTask,
    load_adaptive_research_loop_snapshot,
    run_adaptive_research_loop,
)

_TURN_COUNT = 12
_MODEL_RESERVATION_MILLISECONDS = 300_000
_MECHANICAL_RESERVATION_MILLISECONDS = 1_000
_SPEC_FILENAME = "benchmark-cell-run-spec-v1.json"
_ARTIFACT_FILENAME = "benchmark-cell-run-artifact-v1.json"
_SOURCE_MODULES: dict[str, Any] = {
    "adaptive_loop_benchmark_cell_runner": None,
    "adaptive_loop_benchmark_arm_adapters": arm_adapter_module,
    "adaptive_loop_benchmark_context": context_module,
    "adaptive_loop_benchmark_receipts": receipt_module,
    "adaptive_sovereign_loop": loop_module,
}


class AdaptiveLoopBenchmarkCellRunError(RuntimeError):
    """Raised when a diagnostic cell cannot be replayed exactly."""


class InjectedDiagnosticCompletion(Protocol):
    """Local completion boundary; the marker prevents accidental live use."""

    diagnostic_only: Literal[True]

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult: ...


class BenchmarkCellManifestEntry(KernelContract):
    """One content-addressed leaf in a final raw or controller manifest."""

    entry_id: str = Field(min_length=1, max_length=2_048)
    content_sha256: Sha256


class BenchmarkCellEvidenceManifest(KernelContract):
    """Final evidence inventory; raw bytes stay in the private append-only store."""

    schema_version: Literal["adaptive-loop-benchmark-cell-evidence-manifest-v1"] = (
        "adaptive-loop-benchmark-cell-evidence-manifest-v1"
    )
    plane: Literal["audit_raw", "controller_visible"]
    cell_binding_hash: Sha256
    entries: list[BenchmarkCellManifestEntry] = Field(min_length=1, max_length=512)
    entry_count: int = Field(ge=1, le=512)
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> BenchmarkCellEvidenceManifest:
        if self.entry_count != len(self.entries):
            raise ValueError("cell evidence manifest entry count mismatch")
        if len({item.entry_id for item in self.entries}) != len(self.entries):
            raise ValueError("cell evidence manifest entry IDs must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))
        if self.manifest_hash != expected:
            raise ValueError("cell evidence manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkCellEvidenceManifest:
        payload = {
            "schema_version": "adaptive-loop-benchmark-cell-evidence-manifest-v1",
            **values,
        }
        payload["entries"] = [
            item.model_dump(mode="json") if isinstance(item, BenchmarkCellManifestEntry) else item
            for item in payload["entries"]
        ]
        return cls(
            **payload,
            manifest_hash=canonical_sha256(payload),
        )


class BenchmarkCellRunSpecContent(KernelContract):
    """All result-blind inputs fixed before a diagnostic completion is called."""

    schema_version: Literal["adaptive-loop-benchmark-cell-run-spec-v1"] = (
        "adaptive-loop-benchmark-cell-run-spec-v1"
    )
    execution_track: Literal["diagnostic_double"] = "diagnostic_double"
    receipt_bridge_hash: Sha256
    public_scenario: AdaptiveLoopBenchmarkPublicScenario
    blinded_cell: AdaptiveLoopBenchmarkBlindedCell
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding
    arm_runtime_plan: BenchmarkArmRuntimePlan
    seed: AdaptiveResearchSeed
    policy: AdaptiveLoopPolicy
    seed_sha256: Sha256
    policy_sha256: Sha256
    initial_audit_raw_plane_id: StableId
    initial_controller_visible_plane_id: StableId
    initial_audit_raw_plane_manifest_sha256: Sha256
    initial_controller_visible_plane_manifest_sha256: Sha256
    source_module_sha256s: dict[str, Sha256]
    hidden_scoring_loaded: Literal[False] = False
    scoring_requested: Literal[False] = False
    scientific_result_requested: Literal[False] = False
    external_transport_evidence_required_for_formal_track: Literal[True] = True

    @field_validator("source_module_sha256s")
    @classmethod
    def _validate_source_keys(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != set(_SOURCE_MODULES):
            raise ValueError("cell run source-module inventory is incomplete")
        return value

    @model_validator(mode="after")
    def _validate_inputs(self) -> BenchmarkCellRunSpecContent:
        if self.seed_sha256 != canonical_sha256(self.seed):
            raise ValueError("cell run seed hash mismatch")
        if self.policy_sha256 != canonical_sha256(self.policy):
            raise ValueError("cell run policy hash mismatch")
        if self.policy.max_steps != _TURN_COUNT or self.policy.max_model_calls != _TURN_COUNT:
            raise ValueError("diagnostic cell requires exactly twelve steps and model calls")
        if self.policy.max_external_actions < 1 or self.policy.max_temporary_agents < 1:
            raise ValueError("diagnostic policy must expose the common adaptive capability set")
        if self.seed.objective_cn != self.public_scenario.objective_cn:
            raise ValueError("cell seed objective differs from the public scenario")
        if self.seed.scope_cn != self.public_scenario.scope_cn:
            raise ValueError("cell seed scope differs from the public scenario")
        if (
            self.blinded_cell.blinded_cell_id != self.cell_binding.blinded_cell_id
            or self.blinded_cell.scenario_id != self.cell_binding.scenario_id
            or self.blinded_cell.public_scenario_hash != self.cell_binding.public_scenario_hash
        ):
            raise ValueError("blinded cell and runner binding identify different cells")
        if (
            self.public_scenario.scenario_id != self.cell_binding.scenario_id
            or self.public_scenario.public_scenario_hash != self.cell_binding.public_scenario_hash
        ):
            raise ValueError("public scenario and runner binding identify different scenarios")
        if self.arm_runtime_plan.arm is not self.cell_binding.arm:
            raise ValueError("arm runtime plan differs from the runner-only assignment")
        if self.initial_audit_raw_plane_id == self.initial_controller_visible_plane_id:
            raise ValueError("audit raw and controller-visible plane IDs must differ")
        if self.initial_audit_raw_plane_manifest_sha256 == (
            self.initial_controller_visible_plane_manifest_sha256
        ):
            raise ValueError("initial raw and controller manifests must differ")
        return self


class BenchmarkCellRunSpec(BenchmarkCellRunSpecContent):
    spec_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> BenchmarkCellRunSpec:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"spec_hash"}))
        if self.spec_hash != expected:
            raise ValueError("benchmark cell run spec hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkCellRunSpec:
        content = BenchmarkCellRunSpecContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, spec_hash=canonical_sha256(payload))


class BenchmarkCellRunArtifactContent(KernelContract):
    """Diagnostic cell output; it is process evidence and never a science result."""

    schema_version: Literal["adaptive-loop-benchmark-cell-run-artifact-v1"] = (
        "adaptive-loop-benchmark-cell-run-artifact-v1"
    )
    run_spec: BenchmarkCellRunSpec
    final_snapshot: AdaptiveResearchLoopSnapshot
    event_hashes: list[Sha256] = Field(min_length=_TURN_COUNT, max_length=_TURN_COUNT)
    external_context_hashes: list[Sha256] = Field(
        min_length=_TURN_COUNT,
        max_length=_TURN_COUNT,
    )
    loop_registration_hashes: list[Sha256] = Field(
        min_length=_TURN_COUNT,
        max_length=_TURN_COUNT,
    )
    provider_request_payload_sha256s: list[Sha256] = Field(
        min_length=_TURN_COUNT,
        max_length=_TURN_COUNT,
    )
    declared_completion_providers: list[str] = Field(
        min_length=_TURN_COUNT,
        max_length=_TURN_COUNT,
    )
    declared_completion_models: list[str] = Field(
        min_length=_TURN_COUNT,
        max_length=_TURN_COUNT,
    )
    terminal_action_raw_text: str = Field(min_length=1, max_length=200_000)
    terminal_action_raw_sha256: Sha256
    terminal_action_response_record_hash: Sha256
    audit_raw_final_manifest: BenchmarkCellEvidenceManifest
    controller_visible_final_manifest: BenchmarkCellEvidenceManifest
    arm_realization_audit: BenchmarkArmRealizationAudit
    runtime_evidence: CellRuntimeEvidenceBundle
    journal_entries: list[CellJournalEntry] = Field(min_length=1, max_length=128)
    journal_replay: CellJournalReplay
    terminal_envelope: TerminalEnvelope
    diagnostic_completion_call_count: Literal[12] = 12
    provider_transport_anchor_count: Literal[0] = 0
    actual_sovereign_recall_use_verified: Literal[False] = False
    formal_eligible: Literal[False] = False
    hidden_scoring_loaded: Literal[False] = False
    scoring_not_executed: Literal[True] = True
    scientific_result_generated: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_diagnostic_closure(self) -> BenchmarkCellRunArtifactContent:
        snapshot = self.final_snapshot
        spec = self.run_spec
        if snapshot.seed != spec.seed or snapshot.policy != spec.policy:
            raise ValueError("final snapshot differs from the fixed cell seed or policy")
        if snapshot.status is not AdaptiveLoopRunStatus.PAUSED_BUDGET:
            raise ValueError("diagnostic cell did not terminate at its twelve-turn budget")
        if len(snapshot.events) != _TURN_COUNT or snapshot.model_call_count != _TURN_COUNT:
            raise ValueError("diagnostic cell did not close exactly twelve model turns")
        if self.event_hashes != [item.event_hash for item in snapshot.events]:
            raise ValueError("artifact event hashes differ from the final snapshot")
        contexts = [
            context
            for event in snapshot.events
            for context in event.interaction.external_turn_contexts
        ]
        if len(contexts) != _TURN_COUNT or self.external_context_hashes != [
            item.context_hash for item in contexts
        ]:
            raise ValueError("artifact does not bind one exact public context per turn")
        registrations = [
            registration
            for event in snapshot.events
            for registration in event.interaction.model_call_registrations
        ]
        if len(registrations) != _TURN_COUNT or self.loop_registration_hashes != [
            item.registration_hash for item in registrations
        ]:
            raise ValueError("artifact model-call registrations are incomplete")
        if any(event.interaction.rejected_attempts for event in snapshot.events):
            raise ValueError("diagnostic cell cannot hide repaired or rejected calls")
        try:
            terminal_payload = json.loads(self.terminal_action_raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError("terminal action original text is not exact JSON") from exc
        if terminal_payload != snapshot.events[-1].interaction.proposal.model_dump(mode="json"):
            raise ValueError("terminal action original text differs from the retained proposal")
        if self.terminal_action_raw_sha256 != _sha256_bytes(
            self.terminal_action_raw_text.encode("utf-8")
        ):
            raise ValueError("terminal action original-text hash mismatch")
        if self.audit_raw_final_manifest.plane != "audit_raw":
            raise ValueError("raw final manifest uses the wrong plane")
        if self.controller_visible_final_manifest.plane != "controller_visible":
            raise ValueError("controller final manifest uses the wrong plane")
        if any(
            item.cell_binding_hash != spec.cell_binding.cell_binding_hash
            for item in (
                self.audit_raw_final_manifest,
                self.controller_visible_final_manifest,
            )
        ):
            raise ValueError("final manifests use another cell binding")
        audit = self.arm_realization_audit
        if (
            audit.arm is not spec.arm_runtime_plan.arm
            or audit.plan_hash != spec.arm_runtime_plan.plan_hash
            or audit.snapshot_hash != snapshot.snapshot_hash
            or not audit.capability_matrix_realized
            or audit.actual_sovereign_recall_use_verified
        ):
            raise ValueError("arm realization audit is red or overclaims sovereign recall use")
        runtime = self.runtime_evidence
        if (
            runtime.receipt_bridge_hash != spec.receipt_bridge_hash
            or runtime.cell_binding != spec.cell_binding
            or runtime.arm_attestation.audit_raw_manifest_sha256
            != spec.initial_audit_raw_plane_manifest_sha256
            or runtime.arm_attestation.controller_visible_manifest_sha256
            != spec.initial_controller_visible_plane_manifest_sha256
        ):
            raise ValueError("runtime receipt identity differs from the fixed run spec")
        if runtime.transport_anchors or len(runtime.provider_attempts) != _TURN_COUNT:
            raise ValueError("diagnostic runtime cannot contain transport anchors or missing calls")
        if len(runtime.provider_pre_calls) != _TURN_COUNT:
            raise ValueError("diagnostic runtime pre-call coverage is incomplete")
        if self.provider_request_payload_sha256s != [
            item.request_payload_sha256 for item in runtime.provider_pre_calls
        ]:
            raise ValueError("artifact request hashes differ from diagnostic pre-calls")
        if any(
            item.execution_mode is not ProviderExecutionMode.DIAGNOSTIC_DOUBLE
            or item.formal_eligible
            for item in runtime.provider_attempts
        ):
            raise ValueError("diagnostic attempts cannot become formally eligible")
        if (
            runtime.budget_ledger.declared_charged_total.main_model_requests != _TURN_COUNT
            or len(runtime.budget_ledger.reservations) != _TURN_COUNT + 1
            or len(runtime.budget_ledger.settlements) != _TURN_COUNT + 1
        ):
            raise ValueError("diagnostic budget does not close twelve calls plus mechanics")
        if self.journal_replay.runtime_evidence_hash != runtime.runtime_evidence_hash:
            raise ValueError("journal replay differs from runtime evidence")
        if self.journal_replay.ordered_entry_hashes != [
            item.entry_hash for item in self.journal_entries
        ]:
            raise ValueError("artifact journal entries differ from journal replay")
        terminal = self.terminal_envelope
        if (
            terminal.runtime_evidence_hash != runtime.runtime_evidence_hash
            or terminal.journal_replay_hash != self.journal_replay.replay_hash
            or terminal.formal_eligible
            or terminal.transport_anchor_hashes
            or terminal.scientific_result_generated
        ):
            raise ValueError("diagnostic terminal is not fail-closed")
        return self


class BenchmarkCellRunArtifact(BenchmarkCellRunArtifactContent):
    artifact_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> BenchmarkCellRunArtifact:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise ValueError("benchmark cell run artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkCellRunArtifact:
        content = BenchmarkCellRunArtifactContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, artifact_hash=canonical_sha256(payload))


class _DiagnosticEnvironment:
    """Expose Dreaming for arm isolation but execute no external capability."""

    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset({ResearchOperator.CONSOLIDATE_DREAMING})

    def execute(self, **_: Any) -> ExternalResearchFeedback:
        raise AdaptiveLoopBenchmarkCellRunError(
            "diagnostic cell cannot execute retrieval, probes, or Dreaming"
        )


class _DiagnosticTemporaryDispatcher:
    """Make capability exposure auditable without running a temporary agent."""

    def dispatch(
        self,
        *,
        tasks: Sequence[TemporaryResearchTask],
        **_: Any,
    ) -> TemporaryAgentBatchOutcome:
        del tasks
        raise AdaptiveLoopBenchmarkCellRunError("diagnostic cell cannot execute temporary agents")


class _ReceiptRecordingDiagnosticCompletion:
    def __init__(
        self,
        *,
        completion: InjectedDiagnosticCompletion,
        attestation: ArmRuntimeAttestation,
    ) -> None:
        self._completion = completion
        self._attestation = attestation
        self.reservations: list[BudgetReservation] = []
        self.pre_calls: list[ProviderPreCallAnchor] = []
        self.attempts: list[ProviderAttemptReceipt] = []
        self.walltimes_ms: list[int] = []
        self.request_payloads: list[bytes] = []
        self.messages_sha256s: list[str] = []
        self.declared_providers: list[str] = []
        self.declared_models: list[str] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        call_index = len(self.reservations) + 1
        if call_index > _TURN_COUNT:
            raise AdaptiveLoopBenchmarkCellRunError(
                "diagnostic completion exceeded the frozen twelve calls"
            )
        messages = kwargs.get("messages")
        if not isinstance(messages, list):
            raise AdaptiveLoopBenchmarkCellRunError("diagnostic completion lacks messages")
        request_payload = _diagnostic_request_payload(kwargs)
        reservation = build_budget_reservation(
            attestation=self._attestation,
            reservation_id=f"diag-main-{call_index:02d}",
            operation_kind=BudgetOperationKind.MAIN_MODEL_REQUEST,
            maximum_wall_time_milliseconds=_MODEL_RESERVATION_MILLISECONDS,
        )
        pre_call = build_provider_pre_call_anchor(
            attestation=self._attestation,
            reservation=reservation,
            pre_call_id=f"diag-precall-{call_index:02d}",
            execution_mode=ProviderExecutionMode.DIAGNOSTIC_DOUBLE,
            model_name="diagnostic-double",
            request_payload=request_payload,
        )
        self.reservations.append(reservation)
        self.pre_calls.append(pre_call)
        self.request_payloads.append(request_payload)
        self.messages_sha256s.append(canonical_sha256(messages))

        started = time.perf_counter_ns()
        result = self._completion(**kwargs)
        elapsed_ms = max(1, math.ceil((time.perf_counter_ns() - started) / 1_000_000))
        if elapsed_ms > _MODEL_RESERVATION_MILLISECONDS:
            raise AdaptiveLoopBenchmarkCellRunError(
                "diagnostic completion exceeded its pre-call wall-time reservation"
            )
        if not isinstance(result, LLMJsonCompletionResult):
            raise AdaptiveLoopBenchmarkCellRunError(
                "injected diagnostic completion returned an invalid result"
            )
        reasoning = (result.reasoning_text or "").encode("utf-8")
        usage = canonical_json(result.usage).encode("utf-8")
        attempt = build_provider_attempt_receipt(
            attestation=self._attestation,
            attempt_id=f"diag-attempt-{call_index:02d}",
            request_reservation=reservation,
            pre_call=pre_call,
            status=ProviderAttemptStatus.SUCCEEDED,
            request_payload=request_payload,
            raw_visible_output=result.response_text.encode("utf-8"),
            raw_reasoning=reasoning,
            usage=usage,
            error=None,
        )
        self.attempts.append(attempt)
        self.walltimes_ms.append(elapsed_ms)
        self.declared_providers.append(result.provider)
        self.declared_models.append(result.model_name)
        return result


def build_benchmark_cell_run_spec(
    *,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    public_scenario: AdaptiveLoopBenchmarkPublicScenario,
    blinded_cell: AdaptiveLoopBenchmarkBlindedCell,
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    arm_runtime_plan: BenchmarkArmRuntimePlan,
    seed: AdaptiveResearchSeed,
    policy: AdaptiveLoopPolicy,
) -> BenchmarkCellRunSpec:
    """Validate and content-address every result-blind one-cell input."""

    try:
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
        checked_plan = BenchmarkArmRuntimePlan.model_validate(
            arm_runtime_plan.model_dump(mode="json")
        )
        checked_seed = AdaptiveResearchSeed.model_validate(seed.model_dump(mode="json"))
        checked_policy = AdaptiveLoopPolicy.model_validate(policy.model_dump(mode="json"))
    except (AttributeError, ValueError) as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            f"diagnostic cell input failed canonical validation: {exc}"
        ) from exc
    if checked_bridge.cell(checked_binding.blinded_cell_id) != checked_binding:
        raise AdaptiveLoopBenchmarkCellRunError(
            "runner cell binding is not the exact receipt-bridge leaf"
        )
    bridge_cell = next(
        (
            item
            for item in checked_bridge.blinded_manifest.cells
            if item.blinded_cell_id == checked_cell.blinded_cell_id
        ),
        None,
    )
    if bridge_cell != checked_cell:
        raise AdaptiveLoopBenchmarkCellRunError(
            "blinded cell is not the exact receipt-bridge public cell"
        )
    bridge_scenario = next(
        (
            item
            for item in checked_bridge.execution_protocol.public_scenarios
            if item.scenario_id == checked_scenario.scenario_id
        ),
        None,
    )
    if bridge_scenario != checked_scenario:
        raise AdaptiveLoopBenchmarkCellRunError(
            "public scenario is not the exact receipt-bridge scenario"
        )
    source_hashes = _source_module_hashes()
    plane_ids = _plane_ids(checked_binding)
    raw_manifest, controller_manifest = _initial_plane_manifest_bytes(
        binding=checked_binding,
        plan=checked_plan,
        seed=checked_seed,
        policy=checked_policy,
        source_hashes=source_hashes,
        raw_plane_id=plane_ids[0],
        controller_plane_id=plane_ids[1],
    )
    try:
        return BenchmarkCellRunSpec.create(
            receipt_bridge_hash=checked_bridge.receipt_bridge_hash,
            public_scenario=checked_scenario,
            blinded_cell=checked_cell,
            cell_binding=checked_binding,
            arm_runtime_plan=checked_plan,
            seed=checked_seed,
            policy=checked_policy,
            seed_sha256=canonical_sha256(checked_seed),
            policy_sha256=canonical_sha256(checked_policy),
            initial_audit_raw_plane_id=plane_ids[0],
            initial_controller_visible_plane_id=plane_ids[1],
            initial_audit_raw_plane_manifest_sha256=_sha256_bytes(raw_manifest),
            initial_controller_visible_plane_manifest_sha256=_sha256_bytes(controller_manifest),
            source_module_sha256s=source_hashes,
        )
    except ValueError as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            f"diagnostic cell run spec is invalid: {exc}"
        ) from exc


def run_diagnostic_benchmark_cell(
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
    raw_memory_store: RawMemoryStore,
    completion: InjectedDiagnosticCompletion,
) -> BenchmarkCellRunArtifact:
    """Run and seal one local 12-turn diagnostic cell without scoring it."""

    if getattr(completion, "diagnostic_only", False) is not True:
        raise AdaptiveLoopBenchmarkCellRunError(
            "one-cell diagnostic runner accepts only an explicitly marked local double"
        )
    root = Path(receipt_root).resolve()
    output_root = Path(output_dir).resolve()
    disk_bridge = load_adaptive_loop_benchmark_receipt_bridge(root)
    if disk_bridge != bridge:
        raise AdaptiveLoopBenchmarkCellRunError(
            "supplied receipt bridge differs from the sealed runner bridge"
        )
    spec = build_benchmark_cell_run_spec(
        bridge=bridge,
        public_scenario=public_scenario,
        blinded_cell=blinded_cell,
        cell_binding=cell_binding,
        arm_runtime_plan=arm_runtime_plan,
        seed=seed,
        policy=policy,
    )
    _require_fresh_output_root(output_root)
    _write_contract_once(output_root / _SPEC_FILENAME, spec)

    raw_plane_manifest, controller_plane_manifest = _initial_plane_manifest_bytes(
        binding=spec.cell_binding,
        plan=spec.arm_runtime_plan,
        seed=spec.seed,
        policy=spec.policy,
        source_hashes=spec.source_module_sha256s,
        raw_plane_id=spec.initial_audit_raw_plane_id,
        controller_plane_id=spec.initial_controller_visible_plane_id,
    )
    attestation = build_arm_runtime_attestation(
        bridge=bridge,
        blinded_cell_id=spec.cell_binding.blinded_cell_id,
        audit_raw_memory_plane_id=spec.initial_audit_raw_plane_id,
        controller_visible_memory_plane_id=spec.initial_controller_visible_plane_id,
        audit_raw_manifest=raw_plane_manifest,
        controller_visible_manifest=controller_plane_manifest,
    )
    recorder = _ReceiptRecordingDiagnosticCompletion(
        completion=completion,
        attestation=attestation,
    )
    context_adapter = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=spec.public_scenario,
        blinded_cell=spec.blinded_cell,
        raw_memory_store=raw_memory_store,
    )
    arm_adapter = build_benchmark_arm_adapter(spec.arm_runtime_plan.arm)
    if arm_adapter.plan != spec.arm_runtime_plan:
        raise AdaptiveLoopBenchmarkCellRunError(
            "runtime arm adapter does not reproduce the fixed run plan"
        )
    loop_output = output_root / "loop"
    final_snapshot = run_adaptive_research_loop(
        seed=spec.seed,
        policy=spec.policy,
        raw_memory_store=raw_memory_store,
        output_dir=loop_output,
        environment=_DiagnosticEnvironment(),
        operator_catalog_provider=arm_adapter,
        external_turn_context_provider=context_adapter,
        temporary_dispatcher=_DiagnosticTemporaryDispatcher(),
        completion=recorder,
        clock=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    replayed_snapshot = _replay_completed_loop(
        output_root=loop_output,
        raw_memory_store=raw_memory_store,
        snapshot=final_snapshot,
        recorder=recorder,
    )
    arm_audit = audit_benchmark_arm_realization(
        plan=spec.arm_runtime_plan,
        snapshot=replayed_snapshot,
        artifact_root=loop_output,
    )
    if not arm_audit.capability_matrix_realized:
        raise AdaptiveLoopBenchmarkCellRunError(
            "diagnostic trajectory failed the arm realization audit: "
            + "；".join(arm_audit.findings_cn)
        )
    if arm_audit.actual_sovereign_recall_use_verified:
        raise AdaptiveLoopBenchmarkCellRunError(
            "diagnostic arm audit cannot claim actual sovereign recall use"
        )

    raw_final_manifest = _build_raw_final_manifest(
        binding=spec.cell_binding,
        snapshot=replayed_snapshot,
        raw_memory_store=raw_memory_store,
    )
    controller_final_manifest = _build_controller_final_manifest(
        binding=spec.cell_binding,
        snapshot=replayed_snapshot,
    )
    terminal_text, terminal_record_hash = _terminal_action_original(
        snapshot=replayed_snapshot,
        raw_memory_store=raw_memory_store,
    )
    runtime, entries, journal_replay, terminal = _build_and_write_receipts(
        receipt_root=root,
        bridge=bridge,
        spec=spec,
        attestation=attestation,
        recorder=recorder,
        final_snapshot=replayed_snapshot,
    )
    artifact = BenchmarkCellRunArtifact.create(
        run_spec=spec,
        final_snapshot=replayed_snapshot,
        event_hashes=[item.event_hash for item in replayed_snapshot.events],
        external_context_hashes=[
            context.context_hash
            for event in replayed_snapshot.events
            for context in event.interaction.external_turn_contexts
        ],
        loop_registration_hashes=[
            registration.registration_hash
            for event in replayed_snapshot.events
            for registration in event.interaction.model_call_registrations
        ],
        provider_request_payload_sha256s=[
            _sha256_bytes(item) for item in recorder.request_payloads
        ],
        declared_completion_providers=recorder.declared_providers,
        declared_completion_models=recorder.declared_models,
        terminal_action_raw_text=terminal_text,
        terminal_action_raw_sha256=_sha256_bytes(terminal_text.encode("utf-8")),
        terminal_action_response_record_hash=terminal_record_hash,
        audit_raw_final_manifest=raw_final_manifest,
        controller_visible_final_manifest=controller_final_manifest,
        arm_realization_audit=arm_audit,
        runtime_evidence=runtime,
        journal_entries=entries,
        journal_replay=journal_replay,
        terminal_envelope=terminal,
        diagnostic_completion_call_count=12,
        provider_transport_anchor_count=0,
        actual_sovereign_recall_use_verified=False,
        formal_eligible=False,
        hidden_scoring_loaded=False,
        scoring_not_executed=True,
        scientific_result_generated=False,
        publication_authorized=False,
    )
    _write_contract_once(output_root / _ARTIFACT_FILENAME, artifact)
    return artifact


def load_benchmark_cell_run_artifact(
    path: Path | str,
) -> BenchmarkCellRunArtifact:
    """Load a canonical diagnostic artifact; disk/runtime replay is done at run time."""

    artifact_path = Path(path).resolve()
    try:
        raw = artifact_path.read_bytes()
        artifact = BenchmarkCellRunArtifact.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            f"cannot load benchmark cell run artifact: {exc}"
        ) from exc
    if raw != (canonical_json(artifact) + "\n").encode("utf-8"):
        raise AdaptiveLoopBenchmarkCellRunError("benchmark cell run artifact JSON is not canonical")
    return artifact


def _diagnostic_request_payload(kwargs: Mapping[str, Any]) -> bytes:
    messages = kwargs.get("messages")
    response_schema = kwargs.get("response_schema")
    payload = {
        "schema_version": "adaptive-loop-diagnostic-request-v1",
        "messages": messages,
        "response_schema": response_schema,
        "response_schema_name": kwargs.get("response_schema_name"),
        "timeout_seconds": kwargs.get("timeout_seconds"),
        "max_tokens": kwargs.get("max_tokens"),
        "temperature": kwargs.get("temperature"),
        "thinking_mode": kwargs.get("thinking_mode"),
        "thinking_budget": kwargs.get("thinking_budget"),
        "execution_mode": "diagnostic_double",
    }
    try:
        return canonical_json(payload).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            f"diagnostic request is not canonically serializable: {exc}"
        ) from exc


def _replay_completed_loop(
    *,
    output_root: Path,
    raw_memory_store: RawMemoryStore,
    snapshot: AdaptiveResearchLoopSnapshot,
    recorder: _ReceiptRecordingDiagnosticCompletion,
) -> AdaptiveResearchLoopSnapshot:
    if (
        snapshot.status is not AdaptiveLoopRunStatus.PAUSED_BUDGET
        or len(snapshot.events) != _TURN_COUNT
        or snapshot.model_call_count != _TURN_COUNT
        or len(recorder.attempts) != _TURN_COUNT
    ):
        raise AdaptiveLoopBenchmarkCellRunError(
            "diagnostic cell did not complete exactly twelve accepted turns"
        )
    final_path = output_root / "snapshots" / f"step-0012-{snapshot.snapshot_hash}.json"
    try:
        replayed = load_adaptive_research_loop_snapshot(
            final_path,
            raw_memory_store=raw_memory_store,
        )
    except AdaptiveResearchLoopError as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            f"completed diagnostic loop failed raw/snapshot replay: {exc}"
        ) from exc
    if replayed != snapshot:
        raise AdaptiveLoopBenchmarkCellRunError(
            "on-disk final snapshot differs from the returned loop snapshot"
        )
    for event, message_hash in zip(
        replayed.events,
        recorder.messages_sha256s,
        strict=True,
    ):
        if len(event.interaction.model_call_registrations) != 1:
            raise AdaptiveLoopBenchmarkCellRunError(
                "diagnostic cell used a repair call or lacks a call registration"
            )
        registration = event.interaction.model_call_registrations[0]
        if registration.messages_sha256 != message_hash:
            raise AdaptiveLoopBenchmarkCellRunError(
                "receipt request messages differ from the loop registration"
            )
        registration_path = (
            output_root
            / "action-call-registrations"
            / f"step-{event.step_index:04d}"
            / (f"attempt-01-{registration.registration_hash}.json")
        )
        _require_canonical_contract_file(registration_path, registration)
        event_path = output_root / "events" / f"step-{event.step_index:04d}-{event.event_hash}.json"
        _require_canonical_contract_file(event_path, event)
        if len(event.interaction.external_turn_contexts) != 1:
            raise AdaptiveLoopBenchmarkCellRunError(
                "diagnostic cell lacks one exact public context per turn"
            )
        if event.interaction.rejected_attempts:
            raise AdaptiveLoopBenchmarkCellRunError(
                "diagnostic cell contains an unbudgeted repair trajectory"
            )
    return replayed


def _build_raw_final_manifest(
    *,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    snapshot: AdaptiveResearchLoopSnapshot,
    raw_memory_store: RawMemoryStore,
) -> BenchmarkCellEvidenceManifest:
    prefix = f"adaptive-loop:{snapshot.seed.loop_id}:"
    expected_refs = {f"{prefix}user-seed"}
    expected_registration_payloads: dict[str, bytes] = {}
    for event in snapshot.events:
        step = event.step_index
        expected_refs.update(
            {
                event.interaction.external_turn_contexts[0].source_ref,
                f"{prefix}step:{step}:attempt:1:response",
                f"{prefix}step:{step}:attempt:1:reasoning",
                f"{prefix}step:{step}:transition",
                f"{prefix}step:{step}:action-call-registration:1",
            }
        )
        registration = event.interaction.model_call_registrations[0]
        expected_registration_payloads[f"{prefix}step:{step}:action-call-registration:1"] = (
            canonical_json(registration).encode("utf-8")
        )

    record_root = raw_memory_store.private_root / "projects" / snapshot.seed.project_id / "records"
    captures: dict[str, Any] = {}
    for path in sorted(record_root.glob("*/*/*.json")):
        try:
            capture = raw_memory_store.load_record(
                path.resolve().relative_to(raw_memory_store.vault_root),
                project_id=snapshot.seed.project_id,
            )
        except Exception as exc:
            raise AdaptiveLoopBenchmarkCellRunError(
                f"raw diagnostic record cannot be replayed: {exc}"
            ) from exc
        source_ref = capture.record.envelope.source_ref
        if source_ref.startswith(prefix):
            if source_ref in captures:
                raise AdaptiveLoopBenchmarkCellRunError(
                    "diagnostic raw memory repeats a loop source reference"
                )
            captures[source_ref] = capture
    if set(captures) != expected_refs:
        missing = sorted(expected_refs - set(captures))
        extra = sorted(set(captures) - expected_refs)
        raise AdaptiveLoopBenchmarkCellRunError(
            f"diagnostic raw-memory closure mismatch; missing={missing}, extra={extra}"
        )
    for source_ref, expected_bytes in expected_registration_payloads.items():
        if captures[source_ref].blob_path.read_bytes() != expected_bytes:
            raise AdaptiveLoopBenchmarkCellRunError(
                "raw call registration differs from the retained loop registration"
            )
    entries = [
        BenchmarkCellManifestEntry(
            entry_id=source_ref,
            content_sha256=captures[source_ref].record.record_hash,
        )
        for source_ref in sorted(captures)
    ]
    return BenchmarkCellEvidenceManifest.create(
        plane="audit_raw",
        cell_binding_hash=binding.cell_binding_hash,
        entries=entries,
        entry_count=len(entries),
    )


def _build_controller_final_manifest(
    *,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> BenchmarkCellEvidenceManifest:
    entries = [
        BenchmarkCellManifestEntry(
            entry_id="controller:snapshot:terminal",
            content_sha256=snapshot.snapshot_hash,
        )
    ]
    for event in snapshot.events:
        prefix = f"controller:step:{event.step_index}"
        entries.extend(
            [
                BenchmarkCellManifestEntry(
                    entry_id=f"{prefix}:event",
                    content_sha256=event.event_hash,
                ),
                BenchmarkCellManifestEntry(
                    entry_id=f"{prefix}:interaction",
                    content_sha256=event.interaction.interaction_hash,
                ),
                BenchmarkCellManifestEntry(
                    entry_id=f"{prefix}:messages",
                    content_sha256=event.interaction.messages_sha256,
                ),
                BenchmarkCellManifestEntry(
                    entry_id=f"{prefix}:proposal",
                    content_sha256=canonical_sha256(event.interaction.proposal),
                ),
                BenchmarkCellManifestEntry(
                    entry_id=f"{prefix}:external-context",
                    content_sha256=(event.interaction.external_turn_contexts[0].context_hash),
                ),
                BenchmarkCellManifestEntry(
                    entry_id=f"{prefix}:model-call-registration",
                    content_sha256=(
                        event.interaction.model_call_registrations[0].registration_hash
                    ),
                ),
            ]
        )
    return BenchmarkCellEvidenceManifest.create(
        plane="controller_visible",
        cell_binding_hash=binding.cell_binding_hash,
        entries=entries,
        entry_count=len(entries),
    )


def _terminal_action_original(
    *,
    snapshot: AdaptiveResearchLoopSnapshot,
    raw_memory_store: RawMemoryStore,
) -> tuple[str, str]:
    binding = snapshot.events[-1].interaction.response_binding
    try:
        capture = raw_memory_store.load_record(
            binding.record_relative_path,
            project_id=snapshot.seed.project_id,
        )
        raw = capture.blob_path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            f"terminal action original bytes cannot be replayed: {exc}"
        ) from exc
    if capture.binding(raw_memory_store.vault_root) != binding:
        raise AdaptiveLoopBenchmarkCellRunError("terminal action response binding changed")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            "terminal diagnostic action is not exact JSON"
        ) from exc
    if payload != snapshot.events[-1].interaction.proposal.model_dump(mode="json"):
        raise AdaptiveLoopBenchmarkCellRunError(
            "terminal original response differs from the accepted action"
        )
    return text, capture.record.record_hash


def _build_and_write_receipts(
    *,
    receipt_root: Path,
    bridge: AdaptiveLoopBenchmarkReceiptBridge,
    spec: BenchmarkCellRunSpec,
    attestation: ArmRuntimeAttestation,
    recorder: _ReceiptRecordingDiagnosticCompletion,
    final_snapshot: AdaptiveResearchLoopSnapshot,
) -> tuple[
    CellRuntimeEvidenceBundle,
    list[CellJournalEntry],
    CellJournalReplay,
    TerminalEnvelope,
]:
    if len(recorder.attempts) != _TURN_COUNT:
        raise AdaptiveLoopBenchmarkCellRunError("diagnostic provider receipt count is not twelve")
    mechanical_reservation = build_budget_reservation(
        attestation=attestation,
        reservation_id="diag-mechanical-12-turn-context",
        operation_kind=BudgetOperationKind.MECHANICAL_TRANSITION,
        maximum_wall_time_milliseconds=_MECHANICAL_RESERVATION_MILLISECONDS,
    )
    mechanical = build_mechanical_transition_receipt(
        bridge=bridge,
        attestation=attestation,
        walltime_reservation=mechanical_reservation,
        transition_id="diag-public-context-turns-01-12",
        input_state=canonical_json(spec).encode("utf-8"),
        challenge_fixture=canonical_json(spec.public_scenario).encode("utf-8"),
        output_state=canonical_json(final_snapshot).encode("utf-8"),
    )
    reservations = [*recorder.reservations, mechanical_reservation]
    settlements: list[BudgetLedgerEntry] = []
    for index, (reservation, attempt, elapsed_ms) in enumerate(
        zip(
            recorder.reservations,
            recorder.attempts,
            recorder.walltimes_ms,
            strict=True,
        ),
        start=1,
    ):
        settlements.append(
            build_budget_ledger_entry(
                reservation=reservation,
                sequence=index,
                outcome=BudgetOutcome.SUCCEEDED,
                actual_wall_time_milliseconds=elapsed_ms,
                evidence_receipt_hash=attempt.receipt_hash,
            )
        )
    settlements.append(
        build_budget_ledger_entry(
            reservation=mechanical_reservation,
            sequence=_TURN_COUNT + 1,
            outcome=BudgetOutcome.SUCCEEDED,
            actual_wall_time_milliseconds=1,
            evidence_receipt_hash=mechanical.receipt_hash,
        )
    )
    ledger = build_budget_ledger(
        attestation=attestation,
        budget_limit=BudgetVector(
            main_model_requests=_TURN_COUNT,
            wall_time_milliseconds=(
                _TURN_COUNT * _MODEL_RESERVATION_MILLISECONDS + _MECHANICAL_RESERVATION_MILLISECONDS
            ),
        ),
        reservations=reservations,
        settlements=settlements,
    )
    runtime = build_cell_runtime_evidence_bundle(
        bridge=bridge,
        attestation=attestation,
        budget_ledger=ledger,
        provider_pre_calls=recorder.pre_calls,
        transport_anchors=[],
        provider_attempts=recorder.attempts,
        mechanical_transitions=[mechanical],
    )
    entries = _journal_entries(
        attestation=attestation,
        reservations=recorder.reservations,
        pre_calls=recorder.pre_calls,
        attempts=recorder.attempts,
        settlements=settlements[:-1],
        mechanical_reservation=mechanical_reservation,
        mechanical=mechanical,
        mechanical_settlement=settlements[-1],
    )
    journal_replay = replay_cell_journal(
        bridge=bridge,
        entries=entries,
        runtime_evidence=runtime,
    )
    terminal = build_terminal_envelope(
        bridge=bridge,
        entries=entries,
        runtime_evidence=runtime,
    )
    if terminal.formal_eligible or terminal.transport_anchor_hashes:
        raise AdaptiveLoopBenchmarkCellRunError(
            "diagnostic terminal unexpectedly claims formal provider evidence"
        )
    write_cell_runtime_evidence_once(receipt_root, bridge, runtime)
    for entry in entries:
        write_cell_journal_entry_once(receipt_root, bridge, entry)
    write_terminal_envelope_once(receipt_root, bridge, terminal)
    return runtime, entries, journal_replay, terminal


def _journal_entries(
    *,
    attestation: ArmRuntimeAttestation,
    reservations: Sequence[BudgetReservation],
    pre_calls: Sequence[ProviderPreCallAnchor],
    attempts: Sequence[ProviderAttemptReceipt],
    settlements: Sequence[BudgetLedgerEntry],
    mechanical_reservation: BudgetReservation,
    mechanical: MechanicalChallengeTransitionReceipt,
    mechanical_settlement: BudgetLedgerEntry,
) -> list[CellJournalEntry]:
    entries: list[CellJournalEntry] = []

    def append(kind: CellJournalEventKind, payload_hash: str) -> None:
        entries.append(
            build_cell_journal_entry(
                attestation=attestation,
                event_kind=kind,
                payload_hash=payload_hash,
                previous_entry=entries[-1] if entries else None,
            )
        )

    append(CellJournalEventKind.ARM_ATTESTED, attestation.attestation_hash)
    for reservation, pre_call, attempt, settlement in zip(
        reservations,
        pre_calls,
        attempts,
        settlements,
        strict=True,
    ):
        append(CellJournalEventKind.BUDGET_RESERVED, reservation.reservation_hash)
        append(CellJournalEventKind.PROVIDER_PRECALL_RECORDED, pre_call.pre_call_hash)
        append(CellJournalEventKind.PROVIDER_ATTEMPT_RECORDED, attempt.receipt_hash)
        append(CellJournalEventKind.BUDGET_SETTLED, settlement.entry_hash)
    append(CellJournalEventKind.BUDGET_RESERVED, mechanical_reservation.reservation_hash)
    append(
        CellJournalEventKind.MECHANICAL_TRANSITION_RECORDED,
        mechanical.receipt_hash,
    )
    append(CellJournalEventKind.BUDGET_SETTLED, mechanical_settlement.entry_hash)
    return entries


def _source_module_hashes() -> dict[str, str]:
    paths: dict[str, Path] = {}
    for name, module in _SOURCE_MODULES.items():
        if module is None:
            paths[name] = Path(__file__).resolve()
            continue
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise AdaptiveLoopBenchmarkCellRunError(f"source module {name!r} has no local file")
        paths[name] = Path(module_file).resolve()
    try:
        return {name: _sha256_bytes(path.read_bytes()) for name, path in sorted(paths.items())}
    except OSError as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            f"cannot hash the diagnostic runner source set: {exc}"
        ) from exc


def _plane_ids(
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
) -> tuple[str, str]:
    suffix = binding.cell_binding_hash[:24]
    return f"audit-raw-{suffix}", f"controller-visible-{suffix}"


def _initial_plane_manifest_bytes(
    *,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    plan: BenchmarkArmRuntimePlan,
    seed: AdaptiveResearchSeed,
    policy: AdaptiveLoopPolicy,
    source_hashes: Mapping[str, str],
    raw_plane_id: str,
    controller_plane_id: str,
) -> tuple[bytes, bytes]:
    common = {
        "cell_binding_hash": binding.cell_binding_hash,
        "plan_hash": plan.plan_hash,
        "seed_sha256": canonical_sha256(seed),
        "policy_sha256": canonical_sha256(policy),
        "source_module_sha256s": dict(source_hashes),
    }
    raw = canonical_json(
        {
            "schema_version": "adaptive-loop-initial-audit-raw-plane-v1",
            "plane_id": raw_plane_id,
            "append_only": True,
            "controller_mutation_allowed": False,
            **common,
        }
    ).encode("utf-8")
    controller = canonical_json(
        {
            "schema_version": "adaptive-loop-initial-controller-plane-v1",
            "plane_id": controller_plane_id,
            "derived_and_rebuildable": True,
            "audit_raw_mutation_allowed": False,
            **common,
        }
    ).encode("utf-8")
    return raw, controller


def _require_fresh_output_root(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise AdaptiveLoopBenchmarkCellRunError("diagnostic cell output directory is not fresh")
    path.mkdir(parents=True, exist_ok=True)


def _require_canonical_contract_file(path: Path, contract: KernelContract) -> None:
    expected = (canonical_json(contract) + "\n").encode("utf-8")
    try:
        actual = path.read_bytes()
    except OSError as exc:
        raise AdaptiveLoopBenchmarkCellRunError(
            f"required diagnostic loop artifact is missing: {path.name}"
        ) from exc
    if actual != expected:
        raise AdaptiveLoopBenchmarkCellRunError(f"diagnostic loop artifact changed: {path.name}")


def _write_contract_once(path: Path, contract: KernelContract) -> None:
    payload = (canonical_json(contract) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise AdaptiveLoopBenchmarkCellRunError(
                f"cannot verify write-once diagnostic artifact: {path.name}"
            ) from exc
        if existing != payload:
            raise AdaptiveLoopBenchmarkCellRunError(
                f"write-once diagnostic artifact conflict: {path.name}"
            ) from None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "AdaptiveLoopBenchmarkCellRunError",
    "BenchmarkCellEvidenceManifest",
    "BenchmarkCellManifestEntry",
    "BenchmarkCellRunArtifact",
    "BenchmarkCellRunSpec",
    "InjectedDiagnosticCompletion",
    "build_benchmark_cell_run_spec",
    "load_benchmark_cell_run_artifact",
    "run_diagnostic_benchmark_cell",
]
