"""Formal, fail-closed proof that an A4 cell observably used sovereign recall.

The receipt in this module is intentionally narrower than a memory benchmark
result.  It proves an externally observable chain only:

``early public bytes -> deterministic Dreaming -> signed later request ->
structured terminal consumption claim``.

It does not infer use from prose substrings, an exposed capability, or a model's
hidden state.  It also does not establish that memory improved the answer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import (
    RawMemoryBinding,
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_benchmark_arm_adapters import (
    BenchmarkArmRuntimePlan,
    audit_benchmark_arm_realization,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkBlindedCell,
    AdaptiveLoopBenchmarkPublicScenario,
)
from autoresearch.research.adaptive_loop_benchmark_receipts import (
    AdaptiveLoopBenchmarkCellExecutionBinding,
)
from autoresearch.research.adaptive_memory_loop_audit import (
    AdaptiveMemoryLoopAudit,
    audit_adaptive_memory_loop,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveExternalTurnContext,
    AdaptiveLoopEvent,
    AdaptiveResearchLoopSnapshot,
    ModelMemoryConsumptionClaim,
    ResearchOperator,
    load_adaptive_research_loop_snapshot,
)
from autoresearch.research.adaptive_sovereign_recall import SovereignRecallSelection
from autoresearch.research.adaptive_transport_gateway import (
    AdaptiveTransportGatewayReceipt,
    PostRunAdaptiveTransportGatewayReplay,
    SignedAdaptiveTransportGatewayReceipt,
    TransportGatewayReplayLedger,
    VerifiedAdaptiveTransportGatewayAttestation,
    replay_verify_adaptive_transport_gateway_attestation,
)

_TURN_COUNT = 12
_EARLY_TURNS = (1, 2, 3)
_DREAMING_TURNS = frozenset(range(4, 12))
_RECENT_WINDOW = 8
_SELECTION_FILENAME = "sovereign-recall-selection.json"
_CONTEXT_BINDING_SCHEMA_VERSION = "adaptive-loop-benchmark-public-context-binding-v1"
_CONTEXT_ID_PREFIX = "adaptive-benchmark-context-"


class SovereignRecallUseAuditError(RuntimeError):
    """Raised when supplied lineage is contradictory, altered, or untrustworthy."""


@dataclass(frozen=True)
class SovereignRecallGatewayVerificationPolicy:
    """Out-of-band trust policy for non-consuming terminal replay."""

    trusted_public_key_sha256: str
    trusted_gateway_build_sha256: str
    trusted_gateway_source_sha256: str
    allowlisted_origins: Collection[str]
    replay_ledger: TransportGatewayReplayLedger


class SovereignRecallVerifiedGatewayExchange(KernelContract):
    """Persisted immediate verification evidence replayed without consuming a nonce."""

    schema_version: Literal["sovereign-recall-verified-gateway-exchange-v1"] = (
        "sovereign-recall-verified-gateway-exchange-v1"
    )
    signed_receipt: SignedAdaptiveTransportGatewayReceipt
    verified_attestation: VerifiedAdaptiveTransportGatewayAttestation
    exchange_hash: Sha256

    @model_validator(mode="after")
    def _validate_exchange(self) -> SovereignRecallVerifiedGatewayExchange:
        receipt = self.signed_receipt.receipt
        attestation = self.verified_attestation
        if (
            attestation.receipt_hash != receipt.receipt_hash
            or attestation.envelope_hash != self.signed_receipt.envelope_hash
            or attestation.request_commitment_hash != receipt.request_commitment.commitment_hash
        ):
            raise ValueError("verified gateway exchange hash lineage mismatch")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"exchange_hash"}))
        if self.exchange_hash != expected:
            raise ValueError("verified gateway exchange hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        signed_receipt: SignedAdaptiveTransportGatewayReceipt,
        verified_attestation: VerifiedAdaptiveTransportGatewayAttestation,
    ) -> SovereignRecallVerifiedGatewayExchange:
        payload = {
            "schema_version": "sovereign-recall-verified-gateway-exchange-v1",
            "signed_receipt": signed_receipt.model_dump(mode="json"),
            "verified_attestation": verified_attestation.model_dump(mode="json"),
        }
        return cls(
            signed_receipt=signed_receipt,
            verified_attestation=verified_attestation,
            exchange_hash=canonical_sha256(payload),
        )


class SovereignRecallUseContextEvidence(KernelContract):
    """One exact turn-1--3 public context and its sovereign raw binding."""

    turn_index: int = Field(ge=1, le=3)
    stimulus_id: StableId
    stimulus_hash: Sha256
    context_id: StableId
    context_hash: Sha256
    raw_binding: RawMemoryBinding
    raw_payload_size_bytes: int = Field(ge=1)
    terminal_age_turns: int = Field(ge=9, le=11)
    exact_public_payload_replayed: Literal[True] = True
    same_cell_context_identity_verified: Literal[True] = True

    @model_validator(mode="after")
    def _validate_age(self) -> SovereignRecallUseContextEvidence:
        if self.terminal_age_turns != _TURN_COUNT - self.turn_index:
            raise ValueError("early-context terminal age mismatch")
        return self


class SovereignRecallUseGatewayEvidence(KernelContract):
    """One independently verified provider request/response for an action turn."""

    step_index: int = Field(ge=1, le=12)
    event_hash: Sha256
    interaction_hash: Sha256
    messages_sha256: Sha256
    registration_hash: Sha256
    request_commitment_hash: Sha256
    request_payload_sha256: Sha256
    signed_envelope_hash: Sha256
    gateway_receipt_hash: Sha256
    response_body_sha256: Sha256
    provider_response_model: str = Field(min_length=1, max_length=256)
    provider_response_model_utf8_sha256: Sha256
    visible_output_utf8_sha256: Sha256
    reasoning_output_utf8_sha256: Sha256
    usage_canonical_json_sha256: Sha256
    gateway_attestation_hash: Sha256
    post_run_replay_hash: Sha256
    signature_verified: Literal[True] = True
    provider_completion_eligible: Literal[True] = True
    formal_transport_eligible: Literal[True] = True
    provider_response_model_matches_interaction: Literal[True] = True


class SovereignRecallUseRecordEvidence(KernelContract):
    """Use evidence for one selected early-context record."""

    context_turn_index: int = Field(ge=1, le=3)
    record_id: StableId
    record_hash: Sha256
    payload_sha256: Sha256
    terminal_age_turns: int = Field(ge=9, le=11)
    age_at_dreaming_turns: int = Field(ge=9, le=10)
    selection_hash: Sha256
    excerpt_sha256: Sha256
    dreaming_feedback_hash: Sha256
    later_request_step_index: int | None = Field(default=None, ge=5, le=12)
    later_request_event_hash: Sha256 | None = None
    later_request_interaction_hash: Sha256 | None = None
    later_request_messages_sha256: Sha256 | None = None
    later_request_registration_hash: Sha256 | None = None
    later_gateway_attestation_hash: Sha256 | None = None
    terminal_claim: ModelMemoryConsumptionClaim | None = None
    terminal_claim_hash: Sha256 | None = None
    terminal_event_hash: Sha256
    terminal_interaction_hash: Sha256
    terminal_messages_sha256: Sha256
    terminal_registration_hash: Sha256
    terminal_response_binding: RawMemoryBinding
    terminal_gateway_attestation_hash: Sha256 | None = None
    exact_feedback_exposed_to_later_action_request: bool
    older_than_eight_turns_at_selection: Literal[True] = True
    terminal_raw_structured_consumption_verified: bool
    observable_consumption_chain_verified: bool
    formally_signed_consumption_chain_verified: bool

    @model_validator(mode="after")
    def _validate_chain(self) -> SovereignRecallUseRecordEvidence:
        later_fields = (
            self.later_request_step_index,
            self.later_request_event_hash,
            self.later_request_interaction_hash,
            self.later_request_messages_sha256,
            self.later_request_registration_hash,
        )
        if self.exact_feedback_exposed_to_later_action_request != all(
            value is not None for value in later_fields
        ):
            raise ValueError("later-request feedback evidence is incomplete")
        claim_present = self.terminal_claim is not None
        if claim_present != (self.terminal_claim_hash is not None):
            raise ValueError("terminal memory claim/hash presence mismatch")
        if claim_present and self.terminal_claim_hash != canonical_sha256(self.terminal_claim):
            raise ValueError("terminal memory claim hash mismatch")
        if self.terminal_raw_structured_consumption_verified != claim_present:
            raise ValueError("terminal structured-consumption verdict mismatch")
        expected_observable = (
            self.exact_feedback_exposed_to_later_action_request
            and self.terminal_raw_structured_consumption_verified
        )
        if self.observable_consumption_chain_verified != expected_observable:
            raise ValueError("observable memory-consumption verdict mismatch")
        expected_formal = (
            expected_observable
            and self.later_gateway_attestation_hash is not None
            and self.terminal_gateway_attestation_hash is not None
        )
        if self.formally_signed_consumption_chain_verified != expected_formal:
            raise ValueError("formally signed memory-consumption verdict mismatch")
        return self


class SovereignRecallUseDreamingEvidence(KernelContract):
    """One replayed turn-4--11 Dreaming selection and its eligible early records."""

    dreaming_step_index: int = Field(ge=4, le=11)
    dreaming_event_hash: Sha256
    dreaming_interaction_hash: Sha256
    dreaming_feedback_hash: Sha256
    predecessor_snapshot_hash: Sha256
    predecessor_snapshot_file_sha256: Sha256
    selection_relative_path: str = Field(min_length=1, max_length=1_024)
    selection_hash: Sha256
    selection_file_sha256: Sha256
    memory_audit_hash: Sha256
    selected_record_ids: list[StableId] = Field(min_length=1, max_length=12)
    selected_record_hashes: list[Sha256] = Field(min_length=1, max_length=12)
    selected_payload_sha256s: list[Sha256] = Field(min_length=1, max_length=12)
    selected_early_context_record_count: int = Field(ge=0, le=3)
    selected_older_than_eight_events_count: int = Field(ge=0, le=12)
    record_evidence: list[SovereignRecallUseRecordEvidence] = Field(max_length=3)
    deterministic_selection_replayed: Literal[True] = True
    predecessor_is_exact_trajectory_prefix: Literal[True] = True

    @model_validator(mode="after")
    def _validate_selection(self) -> SovereignRecallUseDreamingEvidence:
        count = len(self.selected_record_ids)
        if not (count == len(self.selected_record_hashes) == len(self.selected_payload_sha256s)):
            raise ValueError("Dreaming selected-record hash lists differ in length")
        if len(self.selected_record_ids) != len(set(self.selected_record_ids)):
            raise ValueError("Dreaming evidence repeats a selected record")
        if self.selected_early_context_record_count != len(self.record_evidence):
            raise ValueError("Dreaming early-context count mismatch")
        if any(item.selection_hash != self.selection_hash for item in self.record_evidence):
            raise ValueError("record evidence belongs to another Dreaming selection")
        return self


class SovereignRecallUseReceiptContent(KernelContract):
    """Scope-limited proof of observable A4 recall use, never a scientific result."""

    schema_version: Literal["sovereign-recall-use-receipt-v1"] = "sovereign-recall-use-receipt-v1"
    blinded_cell_id: StableId
    scenario_id: StableId
    cell_binding_hash: Sha256
    arm: AdaptiveLoopBenchmarkArm
    arm_runtime_plan_hash: Sha256
    arm_realization_audit_hash: Sha256
    trajectory_id: StableId
    public_scenario_hash: Sha256
    final_snapshot_hash: Sha256
    final_snapshot_file_sha256: Sha256
    event_hashes: list[Sha256] = Field(min_length=12, max_length=12)
    context_hashes: list[Sha256] = Field(min_length=12, max_length=12)
    context_record_hashes: list[Sha256] = Field(min_length=12, max_length=12)
    context_payload_sha256s: list[Sha256] = Field(min_length=12, max_length=12)
    early_context_evidence: list[SovereignRecallUseContextEvidence] = Field(
        min_length=3,
        max_length=3,
    )
    memory_audit_hash: Sha256
    dreaming_evidence: list[SovereignRecallUseDreamingEvidence] = Field(max_length=8)
    orphan_selection_paths: list[str] = Field(default_factory=list, max_length=64)
    gateway_evidence: list[SovereignRecallUseGatewayEvidence] = Field(max_length=12)
    all_twelve_public_contexts_replayed: Literal[True] = True
    arm_is_adaptive_sovereign: bool
    arm_capability_matrix_realized: bool
    controller_memory_transport_verified: bool
    early_context_selected_outside_recent_window: bool
    terminal_structured_consumption_verified: bool
    observable_consumption_chain_verified: bool
    all_twelve_provider_actions_independently_signed: bool
    formal_consumption_chain_verified: bool
    actual_sovereign_recall_use_verified: bool
    scientific_result_generated: Literal[False] = False
    causal_memory_benefit_verified: Literal[False] = False
    benchmark_superiority_verified: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False
    findings_cn: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def _validate_verdict(self) -> SovereignRecallUseReceiptContent:
        if [item.turn_index for item in self.early_context_evidence] != [1, 2, 3]:
            raise ValueError("early context evidence must cover turns one through three")
        expected_arm = self.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        if self.arm_is_adaptive_sovereign != expected_arm:
            raise ValueError("A4 arm verdict mismatch")
        expected_old = any(
            item.record_evidence and item.selected_older_than_eight_events_count > 0
            for item in self.dreaming_evidence
        )
        if self.early_context_selected_outside_recent_window != expected_old:
            raise ValueError("old early-context selection verdict mismatch")
        records = [
            record for dreaming in self.dreaming_evidence for record in dreaming.record_evidence
        ]
        expected_terminal = any(
            item.terminal_raw_structured_consumption_verified for item in records
        )
        expected_observable = any(item.observable_consumption_chain_verified for item in records)
        expected_signed = len(self.gateway_evidence) == _TURN_COUNT and [
            item.step_index for item in self.gateway_evidence
        ] == list(range(1, _TURN_COUNT + 1))
        expected_formal_chain = any(
            item.formally_signed_consumption_chain_verified for item in records
        )
        if self.terminal_structured_consumption_verified != expected_terminal:
            raise ValueError("terminal consumption verdict mismatch")
        if self.observable_consumption_chain_verified != expected_observable:
            raise ValueError("observable consumption-chain verdict mismatch")
        if self.all_twelve_provider_actions_independently_signed != expected_signed:
            raise ValueError("signed provider-action coverage verdict mismatch")
        if self.formal_consumption_chain_verified != expected_formal_chain:
            raise ValueError("formal consumption-chain verdict mismatch")
        expected_actual = (
            expected_arm
            and self.arm_capability_matrix_realized
            and self.controller_memory_transport_verified
            and expected_old
            and expected_observable
            and expected_signed
            and expected_formal_chain
            and not self.orphan_selection_paths
        )
        if self.actual_sovereign_recall_use_verified != expected_actual:
            raise ValueError("actual sovereign-recall use verdict mismatch")
        return self


class SovereignRecallUseReceipt(SovereignRecallUseReceiptContent):
    receipt_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> SovereignRecallUseReceipt:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))
        if self.receipt_hash != expected:
            raise ValueError("sovereign recall-use receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SovereignRecallUseReceipt:
        content = SovereignRecallUseReceiptContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, receipt_hash=canonical_sha256(payload))


def audit_sovereign_recall_use(
    snapshot_path: Path | str,
    *,
    public_scenario: AdaptiveLoopBenchmarkPublicScenario,
    blinded_cell: AdaptiveLoopBenchmarkBlindedCell,
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    arm_runtime_plan: BenchmarkArmRuntimePlan,
    raw_memory_store: RawMemoryStore,
    verified_gateway_exchanges: Sequence[SovereignRecallVerifiedGatewayExchange] = (),
    gateway_verification_policy: SovereignRecallGatewayVerificationPolicy | None = None,
    output_path: Path | str | None = None,
) -> SovereignRecallUseReceipt:
    """Replay a twelve-turn cell and build a fail-closed recall-use receipt.

    A1--A3 may be audited to explain their failure, but can never receive a true
    verdict.  Production runners should require this artifact only for A4 and
    require its absence for A1--A3.
    """

    scenario, cell, binding, plan = _validate_benchmark_identity(
        public_scenario,
        blinded_cell,
        cell_binding,
        arm_runtime_plan,
    )
    final_path = Path(snapshot_path).resolve()
    final = load_adaptive_research_loop_snapshot(
        final_path,
        raw_memory_store=raw_memory_store,
    )
    if len(final.events) != _TURN_COUNT or [item.step_index for item in final.events] != list(
        range(1, _TURN_COUNT + 1)
    ):
        raise SovereignRecallUseAuditError("recall-use audit requires exactly twelve turns")
    if final.seed.objective_cn != scenario.objective_cn or final.seed.scope_cn != scenario.scope_cn:
        raise SovereignRecallUseAuditError("loop seed differs from the public scenario")
    if final_path.read_bytes() != (canonical_json(final) + "\n").encode("utf-8"):
        raise SovereignRecallUseAuditError("final snapshot is not canonical immutable JSON")

    contexts, early_contexts = _audit_public_contexts(
        final=final,
        scenario=scenario,
        cell=cell,
        store=raw_memory_store,
    )
    memory_audit = audit_adaptive_memory_loop(
        final_path,
        raw_memory_store=raw_memory_store,
    )
    run_root = final_path.parent.parent.resolve()
    arm_realization = audit_benchmark_arm_realization(
        plan=plan,
        snapshot=final,
        artifact_root=run_root,
    )
    referenced_selection_paths = _referenced_selection_paths(final, run_root)
    discovered_selection_paths = {path.resolve() for path in run_root.rglob(_SELECTION_FILENAME)}
    orphan_paths = sorted(
        path.relative_to(run_root).as_posix()
        for path in discovered_selection_paths - referenced_selection_paths
        if path.is_relative_to(run_root)
    )
    gateway_by_step = _verify_gateway_exchanges(
        final=final,
        binding=binding,
        exchanges=verified_gateway_exchanges,
        policy=gateway_verification_policy,
    )
    dreaming_evidence = _audit_dreaming_events(
        final=final,
        final_path=final_path,
        run_root=run_root,
        memory_audit=memory_audit,
        early_contexts=early_contexts,
        store=raw_memory_store,
        gateway_by_step=gateway_by_step,
    )

    findings: list[str] = []
    if binding.arm is not AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN:
        findings.append("该cell不是A4自适应主权记忆臂，禁止生成实际使用通过结论。")
    if not arm_realization.capability_matrix_realized:
        findings.extend(
            arm_realization.findings_cn or ["轨迹没有机械实现所绑定的benchmark arm能力矩阵。"]
        )
    if orphan_paths:
        findings.append("运行目录含未由对应Dreaming事件唯一绑定的孤儿召回选择制品。")
    if not memory_audit.controller_memory_transport_verified:
        findings.extend(memory_audit.findings_cn or ["确定性主权记忆传输审计未通过。"])
    if not any(item.record_evidence for item in dreaming_evidence):
        findings.append("没有Dreaming选择同cell第1至3轮且终轮年龄超过八轮的公开原始记录。")
    records = [record for dreaming in dreaming_evidence for record in dreaming.record_evidence]
    if not any(item.terminal_raw_structured_consumption_verified for item in records):
        findings.append(
            "第12轮原始模型动作缺少与选择制品五键一致的结构化memory_consumption_claims；"
            "不得以正文子串、source_refs或能力暴露替代。"
        )
    if len(gateway_by_step) != _TURN_COUNT:
        findings.append(
            "尚未逐轮验证12个独立签名gateway成功回执；进程内trace或diagnostic double不能正式通过。"
        )

    old_selected = any(
        item.record_evidence and item.selected_older_than_eight_events_count > 0
        for item in dreaming_evidence
    )
    terminal_verified = any(item.terminal_raw_structured_consumption_verified for item in records)
    observable = any(item.observable_consumption_chain_verified for item in records)
    signed_chain = any(item.formally_signed_consumption_chain_verified for item in records)
    actual = (
        binding.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        and arm_realization.capability_matrix_realized
        and memory_audit.controller_memory_transport_verified
        and old_selected
        and observable
        and len(gateway_by_step) == _TURN_COUNT
        and signed_chain
        and not orphan_paths
    )
    receipt = SovereignRecallUseReceipt.create(
        blinded_cell_id=binding.blinded_cell_id,
        scenario_id=binding.scenario_id,
        cell_binding_hash=binding.cell_binding_hash,
        arm=binding.arm,
        arm_runtime_plan_hash=plan.plan_hash,
        arm_realization_audit_hash=arm_realization.audit_hash,
        trajectory_id=f"trajectory-v3:{binding.cell_binding_hash}",
        public_scenario_hash=scenario.public_scenario_hash,
        final_snapshot_hash=final.snapshot_hash,
        final_snapshot_file_sha256=_sha256_bytes(final_path.read_bytes()),
        event_hashes=[item.event_hash for item in final.events],
        context_hashes=[item.context_hash for item in contexts],
        context_record_hashes=[item.raw_binding.record_hash for item in contexts],
        context_payload_sha256s=[item.raw_binding.payload_sha256 for item in contexts],
        early_context_evidence=early_contexts,
        memory_audit_hash=memory_audit.audit_hash,
        dreaming_evidence=dreaming_evidence,
        orphan_selection_paths=orphan_paths,
        gateway_evidence=[gateway_by_step[index] for index in sorted(gateway_by_step)],
        all_twelve_public_contexts_replayed=True,
        arm_is_adaptive_sovereign=(binding.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN),
        arm_capability_matrix_realized=arm_realization.capability_matrix_realized,
        controller_memory_transport_verified=(memory_audit.controller_memory_transport_verified),
        early_context_selected_outside_recent_window=old_selected,
        terminal_structured_consumption_verified=terminal_verified,
        observable_consumption_chain_verified=observable,
        all_twelve_provider_actions_independently_signed=(len(gateway_by_step) == _TURN_COUNT),
        formal_consumption_chain_verified=signed_chain,
        actual_sovereign_recall_use_verified=actual,
        findings_cn=findings,
    )
    if output_path is not None:
        _write_once(
            Path(output_path),
            (canonical_json(receipt) + "\n").encode("utf-8"),
        )
    return receipt


def _validate_benchmark_identity(
    public_scenario: AdaptiveLoopBenchmarkPublicScenario,
    blinded_cell: AdaptiveLoopBenchmarkBlindedCell,
    cell_binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    plan: BenchmarkArmRuntimePlan,
) -> tuple[
    AdaptiveLoopBenchmarkPublicScenario,
    AdaptiveLoopBenchmarkBlindedCell,
    AdaptiveLoopBenchmarkCellExecutionBinding,
    BenchmarkArmRuntimePlan,
]:
    try:
        scenario = AdaptiveLoopBenchmarkPublicScenario.model_validate(
            public_scenario.model_dump(mode="json")
        )
        cell = AdaptiveLoopBenchmarkBlindedCell.model_validate(blinded_cell.model_dump(mode="json"))
        binding = AdaptiveLoopBenchmarkCellExecutionBinding.model_validate(
            cell_binding.model_dump(mode="json")
        )
        checked_plan = BenchmarkArmRuntimePlan.model_validate(plan.model_dump(mode="json"))
    except (AttributeError, ValueError) as exc:
        raise SovereignRecallUseAuditError(
            f"recall-use benchmark identity is invalid: {exc}"
        ) from exc
    if (
        cell.blinded_cell_id,
        cell.scenario_id,
        cell.public_scenario_hash,
    ) != (
        binding.blinded_cell_id,
        binding.scenario_id,
        binding.public_scenario_hash,
    ):
        raise SovereignRecallUseAuditError("cross-cell benchmark identity substitution")
    if (
        scenario.scenario_id != binding.scenario_id
        or scenario.public_scenario_hash != binding.public_scenario_hash
    ):
        raise SovereignRecallUseAuditError("public scenario differs from the cell binding")
    if checked_plan.arm is not binding.arm:
        raise SovereignRecallUseAuditError("cross-arm runtime-plan substitution")
    if checked_plan.parent_protocol_hash != binding.parent_v1_protocol_hash:
        raise SovereignRecallUseAuditError("arm plan and cell bind different protocols")
    return scenario, cell, binding, checked_plan


def _audit_public_contexts(
    *,
    final: AdaptiveResearchLoopSnapshot,
    scenario: AdaptiveLoopBenchmarkPublicScenario,
    cell: AdaptiveLoopBenchmarkBlindedCell,
    store: RawMemoryStore,
) -> tuple[list[AdaptiveExternalTurnContext], list[SovereignRecallUseContextEvidence]]:
    evidence: list[SovereignRecallUseContextEvidence] = []
    all_contexts: list[AdaptiveExternalTurnContext] = []
    for event, stimulus in zip(final.events, scenario.stimuli, strict=True):
        if len(event.interaction.external_turn_contexts) != 1:
            raise SovereignRecallUseAuditError(
                "every benchmark turn must contain exactly one public context"
            )
        context = event.interaction.external_turn_contexts[0]
        all_contexts.append(context)
        identity = {
            "schema_version": _CONTEXT_BINDING_SCHEMA_VERSION,
            "blinded_cell_id": cell.blinded_cell_id,
            "scenario_id": scenario.scenario_id,
            "public_scenario_hash": scenario.public_scenario_hash,
            "stimulus_id": stimulus.stimulus_id,
            "turn_index": stimulus.turn_index,
            "stimulus_hash": stimulus.stimulus_hash,
            "loop_id": final.seed.loop_id,
            "project_id": final.seed.project_id,
        }
        expected_context_id = f"{_CONTEXT_ID_PREFIX}{canonical_sha256(identity)}"
        expected_ref = (
            f"adaptive-loop:{final.seed.loop_id}:step:{stimulus.turn_index}:"
            f"external-context:{expected_context_id}"
        )
        if (
            context.context_id != expected_context_id
            or context.context_hash
            != canonical_sha256(context.model_dump(mode="json", exclude={"context_hash"}))
            or context.step_index != stimulus.turn_index
            or context.source_ref != expected_ref
            or context.content_cn != stimulus.payload_cn
            or context.content_sha256
            != hashlib.sha256(stimulus.payload_cn.encode("utf-8")).hexdigest()
        ):
            raise SovereignRecallUseAuditError(
                "public context is not the exact same-cell frozen stimulus"
            )
        capture = store.load_record(
            context.raw_binding.record_relative_path,
            project_id=final.seed.project_id,
        )
        raw = capture.blob_path.read_bytes()
        if (
            capture.binding(store.vault_root) != context.raw_binding
            or capture.record.envelope.source_kind is not RawMemorySourceKind.TOOL_OUTPUT
            or capture.record.envelope.source_ref != expected_ref
            or raw != stimulus.payload_cn.encode("utf-8")
        ):
            raise SovereignRecallUseAuditError("public context raw record or payload bytes changed")
        if stimulus.turn_index in _EARLY_TURNS:
            evidence.append(
                SovereignRecallUseContextEvidence(
                    turn_index=stimulus.turn_index,
                    stimulus_id=stimulus.stimulus_id,
                    stimulus_hash=stimulus.stimulus_hash,
                    context_id=context.context_id,
                    context_hash=context.context_hash,
                    raw_binding=context.raw_binding,
                    raw_payload_size_bytes=len(raw),
                    terminal_age_turns=_TURN_COUNT - stimulus.turn_index,
                )
            )
    return all_contexts, evidence


def _referenced_selection_paths(
    final: AdaptiveResearchLoopSnapshot,
    run_root: Path,
) -> set[Path]:
    paths: set[Path] = set()
    for event in final.events:
        refs = [
            item.removeprefix("artifact-path:")
            for item in event.feedback.artifact_refs
            if item.startswith("artifact-path:") and item.endswith(_SELECTION_FILENAME)
        ]
        if event.interaction.proposal.operator is ResearchOperator.CONSOLIDATE_DREAMING:
            if len(refs) != 1:
                raise SovereignRecallUseAuditError(
                    "Dreaming event must bind exactly one recall selection path"
                )
        elif refs:
            raise SovereignRecallUseAuditError("non-Dreaming event cannot bind a recall selection")
        for value in refs:
            relative = PurePosixPath(value.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts or ":" in value:
                raise SovereignRecallUseAuditError("recall selection path is unsafe")
            path = (run_root / Path(relative)).resolve()
            if not path.is_relative_to(run_root):
                raise SovereignRecallUseAuditError("recall selection path escapes run root")
            paths.add(path)
    return paths


def _verify_gateway_exchanges(
    *,
    final: AdaptiveResearchLoopSnapshot,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
    exchanges: Sequence[SovereignRecallVerifiedGatewayExchange],
    policy: SovereignRecallGatewayVerificationPolicy | None,
) -> dict[int, SovereignRecallUseGatewayEvidence]:
    if not exchanges:
        return {}
    if policy is None:
        raise SovereignRecallUseAuditError(
            "verified gateway exchanges require an out-of-band replay policy"
        )
    trajectory_id = f"trajectory-v3:{binding.cell_binding_hash}"
    by_step: dict[int, SovereignRecallUseGatewayEvidence] = {}
    for exchange_input in exchanges:
        try:
            exchange = SovereignRecallVerifiedGatewayExchange.model_validate(
                exchange_input.model_dump(mode="json")
            )
        except (AttributeError, ValueError) as exc:
            raise SovereignRecallUseAuditError(
                f"verified gateway exchange is invalid: {exc}"
            ) from exc
        checked = exchange.signed_receipt
        receipt = checked.receipt
        if not isinstance(receipt, AdaptiveTransportGatewayReceipt):
            raise SovereignRecallUseAuditError(
                "gateway failure receipt cannot prove a provider action"
            )
        commitment = receipt.request_commitment
        if (
            commitment.cell_id != binding.blinded_cell_id
            or commitment.trajectory_id != trajectory_id
        ):
            raise SovereignRecallUseAuditError("signed gateway receipt crosses cell or trajectory")
        matches = [
            event
            for event in final.events
            if len(event.interaction.model_call_registrations) == 1
            and event.interaction.model_call_registrations[0].registration_id
            == commitment.pre_call_id
            and event.interaction.model_call_registrations[0].registration_hash
            == commitment.pre_call_hash
        ]
        if len(matches) != 1:
            raise SovereignRecallUseAuditError(
                "gateway pre-call does not bind one exact action registration"
            )
        event = matches[0]
        registration = event.interaction.model_call_registrations[0]
        if (
            commitment.request_messages_sha256 != event.interaction.messages_sha256
            or commitment.request_messages_sha256 != registration.messages_sha256
        ):
            raise SovereignRecallUseAuditError(
                "gateway request messages differ from the retained provider action request"
            )
        if (
            commitment.provider_name != event.interaction.provider
            or commitment.model_name != event.interaction.model_name
        ):
            raise SovereignRecallUseAuditError(
                "gateway request provider/model differs from the retained interaction"
            )
        if receipt.visible_output_utf8_sha256 != (
            event.interaction.response_binding.payload_sha256
        ) or receipt.reasoning_output_utf8_sha256 != (
            event.interaction.reasoning_binding.payload_sha256
        ):
            raise SovereignRecallUseAuditError(
                "gateway completion hashes differ from sovereign raw model output"
            )
        attestation, post_run_replay = _replay_verified_gateway_exchange(
            exchange,
            policy=policy,
        )
        if event.step_index in by_step:
            raise SovereignRecallUseAuditError(
                "multiple signed gateway receipts claim the same action turn"
            )
        if (
            receipt.visible_output_utf8_sha256 is None
            or receipt.reasoning_output_utf8_sha256 is None
            or receipt.usage_canonical_json_sha256 is None
            or receipt.provider_response_model is None
            or receipt.provider_response_model_utf8_sha256 is None
        ):
            raise SovereignRecallUseAuditError(
                "gateway success receipt lacks completion projection hashes"
            )
        if (
            not receipt.provider_response_model_matches_committed_model
            or receipt.provider_response_model != event.interaction.model_name
        ):
            raise SovereignRecallUseAuditError(
                "provider response model differs from the retained interaction"
            )
        by_step[event.step_index] = SovereignRecallUseGatewayEvidence(
            step_index=event.step_index,
            event_hash=event.event_hash,
            interaction_hash=event.interaction.interaction_hash,
            messages_sha256=event.interaction.messages_sha256,
            registration_hash=registration.registration_hash,
            request_commitment_hash=commitment.commitment_hash,
            request_payload_sha256=commitment.request_payload_sha256,
            signed_envelope_hash=checked.envelope_hash,
            gateway_receipt_hash=receipt.receipt_hash,
            response_body_sha256=receipt.response_body_sha256,
            provider_response_model=receipt.provider_response_model,
            provider_response_model_utf8_sha256=(receipt.provider_response_model_utf8_sha256),
            visible_output_utf8_sha256=receipt.visible_output_utf8_sha256,
            reasoning_output_utf8_sha256=receipt.reasoning_output_utf8_sha256,
            usage_canonical_json_sha256=receipt.usage_canonical_json_sha256,
            gateway_attestation_hash=attestation.attestation_hash,
            post_run_replay_hash=post_run_replay.replay_hash,
        )
    return by_step


def _replay_verified_gateway_exchange(
    exchange: SovereignRecallVerifiedGatewayExchange,
    *,
    policy: SovereignRecallGatewayVerificationPolicy,
) -> tuple[
    VerifiedAdaptiveTransportGatewayAttestation,
    PostRunAdaptiveTransportGatewayReplay,
]:
    """Recheck a previously consumed receipt without consuming its nonce again."""

    signed = exchange.signed_receipt
    receipt = signed.receipt
    if not isinstance(receipt, AdaptiveTransportGatewayReceipt):
        raise SovereignRecallUseAuditError(
            "transport failure cannot be replayed as a provider completion"
        )
    attestation = exchange.verified_attestation
    commitment = receipt.request_commitment
    try:
        replay = replay_verify_adaptive_transport_gateway_attestation(
            signed,
            expected_request_commitment=commitment,
            accepted_attestation=attestation,
            trusted_public_key_sha256=policy.trusted_public_key_sha256,
            trusted_gateway_build_sha256=policy.trusted_gateway_build_sha256,
            trusted_gateway_source_sha256=policy.trusted_gateway_source_sha256,
            allowlisted_origins=policy.allowlisted_origins,
            replay_ledger=policy.replay_ledger,
        )
    except Exception as exc:
        raise SovereignRecallUseAuditError(f"post-run gateway replay failed: {exc}") from exc
    if not replay.provider_completion_eligible:
        raise SovereignRecallUseAuditError("post-run gateway replay is not a provider completion")
    return attestation, replay


def _audit_dreaming_events(
    *,
    final: AdaptiveResearchLoopSnapshot,
    final_path: Path,
    run_root: Path,
    memory_audit: AdaptiveMemoryLoopAudit,
    early_contexts: Sequence[SovereignRecallUseContextEvidence],
    store: RawMemoryStore,
    gateway_by_step: Mapping[int, SovereignRecallUseGatewayEvidence],
) -> list[SovereignRecallUseDreamingEvidence]:
    del final_path
    early_by_record = {item.raw_binding.record_id: item for item in early_contexts}
    terminal = final.events[-1]
    terminal_raw = _terminal_raw_payload(terminal, store, final.seed.project_id)
    result: list[SovereignRecallUseDreamingEvidence] = []
    memory_evidence_by_step = {
        item.dreaming_step_index: item for item in memory_audit.transport_evidence
    }
    for event_index, event in enumerate(final.events):
        if event.interaction.proposal.operator is not ResearchOperator.CONSOLIDATE_DREAMING:
            continue
        if event.step_index not in _DREAMING_TURNS:
            raise SovereignRecallUseAuditError(
                "benchmark Dreaming must occur between turns four and eleven"
            )
        selection_path = next(
            iter(_event_selection_paths(event, run_root)),
            None,
        )
        if selection_path is None:
            raise SovereignRecallUseAuditError("Dreaming selection path is absent")
        raw = selection_path.read_bytes()
        try:
            selection = SovereignRecallSelection.model_validate_json(raw)
        except ValueError as exc:
            raise SovereignRecallUseAuditError(f"Dreaming selection is invalid: {exc}") from exc
        if raw != (canonical_json(selection) + "\n").encode("utf-8"):
            raise SovereignRecallUseAuditError("Dreaming selection is not canonical JSON")
        if (
            selection.loop_id != final.seed.loop_id
            or selection.project_id != final.seed.project_id
            or selection.step_index != event.step_index
            or selection.branch_id != event.branch_id
            or selection.proposal_hash != canonical_sha256(event.interaction.proposal)
            or f"artifact:{selection.selection_hash}" not in event.feedback.artifact_refs
        ):
            raise SovereignRecallUseAuditError(
                "Dreaming selection differs from its event/action binding"
            )
        predecessor_path = (
            run_root
            / "snapshots"
            / (f"step-{event.step_index - 1:04d}-{selection.snapshot_hash}.json")
        )
        predecessor = load_adaptive_research_loop_snapshot(
            predecessor_path,
            raw_memory_store=store,
        )
        if predecessor.events != final.events[:event_index]:
            raise SovereignRecallUseAuditError(
                "Dreaming predecessor is not the exact trajectory prefix"
            )
        memory_transport = memory_evidence_by_step.get(event.step_index)
        if (
            memory_transport is None
            or memory_transport.selection_hash != selection.selection_hash
            or not memory_transport.all_selected_raw_bindings_replayed
            or not memory_transport.selection_artifact_bound_to_feedback
        ):
            raise SovereignRecallUseAuditError(
                "deterministic memory audit does not bind the Dreaming selection: "
                f"step={event.step_index}, evidence_present={memory_transport is not None}, "
                f"selection_matches={memory_transport is not None and memory_transport.selection_hash == selection.selection_hash}, "
                f"raw_replayed={memory_transport is not None and memory_transport.all_selected_raw_bindings_replayed}, "
                f"artifact_bound={memory_transport is not None and memory_transport.selection_artifact_bound_to_feedback}"
            )
        exposure_by_key = {
            (
                item.selection_hash,
                item.record_id,
                item.payload_sha256,
                item.excerpt_sha256,
            ): item
            for item in event.feedback.memory_exposures
        }
        selected_records: list[SovereignRecallUseRecordEvidence] = []
        recent_context_record_ids = {
            context.raw_binding.record_id
            for predecessor_event in predecessor.events[-_RECENT_WINDOW:]
            for context in predecessor_event.interaction.external_turn_contexts
        }
        for excerpt in selection.selected_excerpts:
            context = early_by_record.get(excerpt.binding.record_id)
            if context is None or excerpt.binding.record_id in recent_context_record_ids:
                continue
            age_at_dreaming = event.step_index - context.turn_index
            if age_at_dreaming <= _RECENT_WINDOW:
                raise SovereignRecallUseAuditError(
                    "selected early context is not older than the eight-turn window"
                )
            exposure_key = (
                selection.selection_hash,
                excerpt.binding.record_id,
                excerpt.binding.payload_sha256,
                excerpt.excerpt_sha256,
            )
            exposure = exposure_by_key.get(exposure_key)
            if exposure is None or exposure.excerpt_text != excerpt.excerpt_text:
                raise SovereignRecallUseAuditError(
                    "Dreaming feedback exposure differs from the selected early raw excerpt"
                )
            later = _later_request_exposing_feedback(
                final.events[event_index + 1 :],
                source_event=event,
            )
            claim = _matching_terminal_claim(
                terminal=terminal,
                terminal_raw=terminal_raw,
                dreaming_step=event.step_index,
                selection=selection,
                excerpt=excerpt,
            )
            later_gateway = gateway_by_step.get(later.step_index) if later is not None else None
            terminal_gateway = gateway_by_step.get(_TURN_COUNT)
            selected_records.append(
                SovereignRecallUseRecordEvidence(
                    context_turn_index=context.turn_index,
                    record_id=excerpt.binding.record_id,
                    record_hash=excerpt.binding.record_hash,
                    payload_sha256=excerpt.binding.payload_sha256,
                    terminal_age_turns=context.terminal_age_turns,
                    age_at_dreaming_turns=age_at_dreaming,
                    selection_hash=selection.selection_hash,
                    excerpt_sha256=excerpt.excerpt_sha256,
                    dreaming_feedback_hash=event.feedback.feedback_hash,
                    later_request_step_index=(later.step_index if later else None),
                    later_request_event_hash=(later.event_hash if later else None),
                    later_request_interaction_hash=(
                        later.interaction.interaction_hash if later else None
                    ),
                    later_request_messages_sha256=(
                        later.interaction.messages_sha256 if later else None
                    ),
                    later_request_registration_hash=(
                        later.interaction.model_call_registrations[-1].registration_hash
                        if later
                        else None
                    ),
                    later_gateway_attestation_hash=(
                        later_gateway.gateway_attestation_hash if later_gateway else None
                    ),
                    terminal_claim=claim,
                    terminal_claim_hash=(canonical_sha256(claim) if claim else None),
                    terminal_event_hash=terminal.event_hash,
                    terminal_interaction_hash=terminal.interaction.interaction_hash,
                    terminal_messages_sha256=terminal.interaction.messages_sha256,
                    terminal_registration_hash=(
                        terminal.interaction.model_call_registrations[-1].registration_hash
                    ),
                    terminal_response_binding=terminal.interaction.response_binding,
                    terminal_gateway_attestation_hash=(
                        terminal_gateway.gateway_attestation_hash if terminal_gateway else None
                    ),
                    exact_feedback_exposed_to_later_action_request=later is not None,
                    terminal_raw_structured_consumption_verified=claim is not None,
                    observable_consumption_chain_verified=(later is not None and claim is not None),
                    formally_signed_consumption_chain_verified=(
                        later is not None
                        and claim is not None
                        and later_gateway is not None
                        and terminal_gateway is not None
                    ),
                )
            )
        result.append(
            SovereignRecallUseDreamingEvidence(
                dreaming_step_index=event.step_index,
                dreaming_event_hash=event.event_hash,
                dreaming_interaction_hash=event.interaction.interaction_hash,
                dreaming_feedback_hash=event.feedback.feedback_hash,
                predecessor_snapshot_hash=predecessor.snapshot_hash,
                predecessor_snapshot_file_sha256=_sha256_bytes(predecessor_path.read_bytes()),
                selection_relative_path=selection_path.relative_to(run_root).as_posix(),
                selection_hash=selection.selection_hash,
                selection_file_sha256=_sha256_bytes(raw),
                memory_audit_hash=memory_audit.audit_hash,
                selected_record_ids=[
                    item.binding.record_id for item in selection.selected_excerpts
                ],
                selected_record_hashes=[
                    item.binding.record_hash for item in selection.selected_excerpts
                ],
                selected_payload_sha256s=[
                    item.binding.payload_sha256 for item in selection.selected_excerpts
                ],
                selected_early_context_record_count=len(selected_records),
                selected_older_than_eight_events_count=(
                    memory_transport.selected_older_than_eight_events_count
                ),
                record_evidence=selected_records,
            )
        )
    return result


def _event_selection_paths(event: AdaptiveLoopEvent, run_root: Path) -> set[Path]:
    paths: set[Path] = set()
    for value in (
        item.removeprefix("artifact-path:")
        for item in event.feedback.artifact_refs
        if item.startswith("artifact-path:") and item.endswith(_SELECTION_FILENAME)
    ):
        path = (run_root / Path(PurePosixPath(value.replace("\\", "/")))).resolve()
        if not path.is_relative_to(run_root):
            raise SovereignRecallUseAuditError("Dreaming selection escapes run root")
        paths.add(path)
    if len(paths) != 1:
        raise SovereignRecallUseAuditError("Dreaming event does not bind exactly one selection")
    return paths


def _later_request_exposing_feedback(
    later_events: Sequence[AdaptiveLoopEvent],
    *,
    source_event: AdaptiveLoopEvent,
) -> AdaptiveLoopEvent | None:
    expected = {
        "step_index": source_event.step_index,
        "branch_id": source_event.branch_id,
        "operator": source_event.interaction.proposal.operator.value,
        "feedback_status": source_event.feedback.status.value,
        "feedback_summary_cn": source_event.feedback.summary_cn,
        "feedback_findings_cn": source_event.feedback.findings_cn,
        "memory_exposures": [
            item.model_dump(mode="json") for item in source_event.feedback.memory_exposures
        ],
        "created_branch_id": source_event.created_branch_id,
    }
    for event in later_events:
        task = _task_payload(event.interaction.messages)
        recent = task.get("recent_external_feedback")
        if isinstance(recent, list) and any(item == expected for item in recent):
            return event
    return None


def _matching_terminal_claim(
    *,
    terminal: AdaptiveLoopEvent,
    terminal_raw: dict[str, Any],
    dreaming_step: int,
    selection: SovereignRecallSelection,
    excerpt: Any,
) -> ModelMemoryConsumptionClaim | None:
    raw_claims = terminal_raw.get("memory_consumption_claims")
    if not isinstance(raw_claims, list):
        return None
    proposal_claims = terminal.interaction.proposal.memory_consumption_claims
    if raw_claims != [item.model_dump(mode="json") for item in proposal_claims]:
        raise SovereignRecallUseAuditError(
            "terminal raw response claims differ from the parsed model action"
        )
    expected_key = (
        dreaming_step,
        selection.selection_hash,
        excerpt.binding.record_id,
        excerpt.binding.payload_sha256,
        excerpt.excerpt_sha256,
    )
    matches = [
        item
        for item in proposal_claims
        if (
            item.dreaming_step_index,
            item.selection_hash,
            item.record_id,
            item.payload_sha256,
            item.excerpt_sha256,
        )
        == expected_key
        and item.fact_cn in excerpt.excerpt_text
    ]
    if len(matches) > 1:
        raise SovereignRecallUseAuditError(
            "terminal action repeats one structured memory-consumption claim"
        )
    return matches[0] if matches else None


def _terminal_raw_payload(
    terminal: AdaptiveLoopEvent,
    store: RawMemoryStore,
    project_id: str,
) -> dict[str, Any]:
    capture = store.load_record(
        terminal.interaction.response_binding.record_relative_path,
        project_id=project_id,
    )
    if capture.binding(store.vault_root) != terminal.interaction.response_binding:
        raise SovereignRecallUseAuditError("terminal response raw binding changed")
    payload = _load_duplicate_free_json(capture.blob_path.read_bytes())
    if not isinstance(payload, dict):
        raise SovereignRecallUseAuditError("terminal model response is not a JSON object")
    if payload != terminal.interaction.proposal.model_dump(mode="json"):
        raise SovereignRecallUseAuditError(
            "terminal raw model action differs from the retained proposal"
        )
    return cast(dict[str, Any], payload)


def _task_payload(
    messages: Sequence[dict[Literal["role", "content"], str]],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("context_kind") == (
            "adaptive_research_next_action"
        ):
            candidates.append(cast(dict[str, Any], payload))
    if len(candidates) != 1:
        raise SovereignRecallUseAuditError("provider action request lacks one exact task payload")
    return candidates[0]


def _load_duplicate_free_json(payload: bytes) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SovereignRecallUseAuditError(
            f"terminal raw response is not duplicate-free UTF-8 JSON: {exc}"
        ) from exc


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise SovereignRecallUseAuditError(
                f"immutable sovereign recall-use receipt changed: {path}"
            ) from None


__all__ = [
    "SovereignRecallGatewayVerificationPolicy",
    "SovereignRecallUseAuditError",
    "SovereignRecallUseContextEvidence",
    "SovereignRecallUseDreamingEvidence",
    "SovereignRecallUseGatewayEvidence",
    "SovereignRecallUseReceipt",
    "SovereignRecallUseRecordEvidence",
    "SovereignRecallVerifiedGatewayExchange",
    "audit_sovereign_recall_use",
]
