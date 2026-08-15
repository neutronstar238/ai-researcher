from __future__ import annotations

import base64
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autoresearch.kernel.contracts import canonical_json, canonical_sha256
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.adaptive_capabilities import (
    AdaptiveResearchCapabilityEnvironment,
)
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_benchmark_arm_adapters import (
    BenchmarkArmRuntimePlan,
    build_benchmark_arm_adapter,
    build_benchmark_arm_runtime_plan,
)
from autoresearch.research.adaptive_loop_benchmark_context import (
    AdaptiveLoopBenchmarkPublicContextAdapter,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkBlindedCell,
    AdaptiveLoopBenchmarkExecutionBundle,
    AdaptiveLoopBenchmarkPublicScenario,
    write_adaptive_loop_benchmark_execution_protocol,
)
from autoresearch.research.adaptive_loop_benchmark_receipts import (
    AdaptiveLoopBenchmarkCellExecutionBinding,
    AdaptiveLoopBenchmarkReceiptBridge,
    write_adaptive_loop_benchmark_receipt_bridge_once,
)
from autoresearch.research.adaptive_memory_loop_audit import AdaptiveMemoryLoopAuditError
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveResearchLoopSnapshot,
    ModelMemoryConsumptionClaim,
    ModelResearchActionDraft,
    ResearchOperator,
    create_adaptive_research_seed,
    run_adaptive_research_loop,
)
from autoresearch.research.adaptive_sovereign_recall import SovereignRecallSelection
from autoresearch.research.adaptive_sovereign_recall_use import (
    SovereignRecallGatewayVerificationPolicy,
    SovereignRecallUseAuditError,
    SovereignRecallUseReceipt,
    SovereignRecallVerifiedGatewayExchange,
    audit_sovereign_recall_use,
)
from autoresearch.research.adaptive_transport_gateway import (
    TransportGatewayReplayLedger,
    build_adaptive_transport_gateway_receipt,
    build_signed_adaptive_transport_gateway_receipt,
    build_transport_gateway_request_commitment,
    transport_gateway_receipt_signature_message,
    verify_adaptive_transport_gateway_receipt,
)

_NOW = datetime(2026, 8, 10, 4, 0, 2, tzinfo=timezone.utc)
_ISSUED = "2026-08-10T04:00:00Z"
_COMPLETED = "2026-08-10T04:00:01Z"
_ORIGIN = "https://api.example.com"
_URL = f"{_ORIGIN}/v1/chat/completions"
_BUILD_HASH = hashlib.sha256(b"test-gateway-build").hexdigest()
_SOURCE_HASH = hashlib.sha256(b"test-gateway-source").hexdigest()
_REASONING = (
    "我先核对本轮公开刺激、最近反馈和开放算子，再自主选择当前信息增益最高的动作。"
    "所有召回内容都只是可追溯线索，不是正确性、因果收益、创新性或可发表性的证明。"
    "若结构化记忆暴露存在，只在确实改变终轮判断时按原始五键声明使用。"
) * 3


@dataclass(frozen=True)
class _Run:
    root: Path
    final_path: Path
    store: RawMemoryStore
    scenario: AdaptiveLoopBenchmarkPublicScenario
    cell: AdaptiveLoopBenchmarkBlindedCell
    binding: AdaptiveLoopBenchmarkCellExecutionBinding
    plan: BenchmarkArmRuntimePlan
    snapshot: AdaptiveResearchLoopSnapshot


class _TwelveTurnCompletion:
    def __init__(
        self,
        *,
        target_payload: str,
        dreaming: bool,
        select_early: bool,
        terminal_claim: bool,
    ) -> None:
        self.target_payload = target_payload
        self.dreaming = dreaming
        self.select_early = select_early
        self.terminal_claim = terminal_claim
        self.calls = 0

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls += 1
        task = json.loads(kwargs["messages"][-1]["content"])
        step = int(task["step_index"])
        operator = (
            ResearchOperator.CONSOLIDATE_DREAMING
            if self.dreaming and step == 10
            else ResearchOperator.DECOMPOSE_UNCERTAINTY
        )
        if step == 10 and self.select_early:
            title = "召回第一轮精确公开观察"
            body = f"从完整原始记录召回并核对这一早期观察：{self.target_payload}"
        elif step == 10:
            title = "玄鲸斑驳"
            body = "玄鲸斑驳，只测试没有词项重合时的确定性召回回退。"
        else:
            title = f"第{step}轮自主拆解未知量"
            body = "继续区分公开观察、待核线索和仍未验证的解释，不生成隐藏评分答案。"
        claims: list[ModelMemoryConsumptionClaim] = []
        if step == 12 and self.terminal_claim:
            exposures = [
                exposure
                for feedback in task["recent_external_feedback"]
                for exposure in feedback.get("memory_exposures", [])
            ]
            matching = [item for item in exposures if item["excerpt_text"] == self.target_payload]
            assert matching, "turn-12 test action must see the selected early exposure"
            exposure = matching[0]
            claims = [
                ModelMemoryConsumptionClaim(
                    dreaming_step_index=exposure["dreaming_step_index"],
                    selection_hash=exposure["selection_hash"],
                    record_id=exposure["record_id"],
                    payload_sha256=exposure["payload_sha256"],
                    excerpt_sha256=exposure["excerpt_sha256"],
                    fact_cn=exposure["excerpt_text"],
                    application_cn=(
                        "该早期公开观察改变了终轮的证据取舍，因此保留其精确来源并拒绝按近期干扰改写。"
                    ),
                    model_declared_consumption_only=True,
                    establishes_causal_memory_benefit=False,
                    is_scientific_evidence=False,
                )
            ]
        proposal = ModelResearchActionDraft(
            schema_version="adaptive-research-action-draft-v3",
            step_index=step,
            branch_id=str(task["selected_branch"]["branch_id"]),
            operator=operator,
            action_title_cn=title,
            action_body_cn=body,
            retrieval_query_terms=[],
            reason_for_choice_cn="该动作在当前机械预算内最可能减少一个明确未知量。",
            expected_information_gain_cn="能够检验旧线索是否进入后续请求并改变终轮显式判断。",
            memory_consumption_claims=claims,
        ).model_dump(mode="json")
        response = json.dumps(proposal, ensure_ascii=False, sort_keys=True)
        return LLMJsonCompletionResult(
            provider="qwen",
            base_url=_ORIGIN,
            model_name="qwen3-test",
            endpoint=_URL,
            response_text=response,
            parsed_json=proposal,
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            temperature=0.7,
            reasoning_text=_REASONING,
            reasoning_transport="dashscope_enable_thinking",
        )


class _UnusedTemporaryDispatcher:
    def dispatch(self, **_: Any) -> Any:
        raise AssertionError("the 12-turn recall-use fixture never selects temporary dispatch")


@pytest.fixture(scope="module")
def protocol(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, AdaptiveLoopBenchmarkExecutionBundle, AdaptiveLoopBenchmarkReceiptBridge]:
    root = tmp_path_factory.mktemp("recall-use-protocol")
    bundle = write_adaptive_loop_benchmark_execution_protocol(
        root,
        randomization_seed=27_132_026,
    )
    bridge = write_adaptive_loop_benchmark_receipt_bridge_once(root, bundle)
    return root, bundle, bridge


def _run(
    root: Path,
    *,
    protocol: tuple[
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    arm: AdaptiveLoopBenchmarkArm,
    select_early: bool,
    terminal_claim: bool,
) -> _Run:
    _, bundle, bridge = protocol
    scenario = bundle.protocol.public_scenarios[0]
    binding = next(
        item
        for item in bridge.cells
        if item.scenario_id == scenario.scenario_id and item.arm is arm
    )
    cell = next(
        item
        for item in bundle.blinded_cells.cells
        if item.blinded_cell_id == binding.blinded_cell_id
    )
    store = RawMemoryStore(root / "vault")
    seed = create_adaptive_research_seed(
        loop_id=f"recall-use-{arm.value}-{canonical_sha256(str(root))[:12]}",
        project_id=f"recall_use_{canonical_sha256(str(root))[:16]}",
        objective_cn=scenario.objective_cn,
        scope_cn=scenario.scope_cn,
        raw_memory_store=store,
        captured_at=_NOW,
    )
    output = root / "run"
    completion = _TwelveTurnCompletion(
        target_payload=scenario.stimuli[0].payload_cn,
        dreaming=(arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN),
        select_early=select_early,
        terminal_claim=terminal_claim,
    )
    plan = build_benchmark_arm_runtime_plan(arm)
    snapshot = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="recall-use-test-policy",
            max_steps=12,
            max_model_calls=12,
            max_external_actions=12,
            max_temporary_agents=14,
            max_consecutive_stalls=20,
        ),
        raw_memory_store=store,
        output_dir=output,
        environment=AdaptiveResearchCapabilityEnvironment(
            output_dir=output,
            raw_memory_store=store,
            literature_clients={"unused": object()},
            clock=lambda: _NOW,
        ),
        operator_catalog_provider=build_benchmark_arm_adapter(arm),
        temporary_dispatcher=(
            _UnusedTemporaryDispatcher() if plan.temporary_dispatch_enabled else None
        ),
        external_turn_context_provider=AdaptiveLoopBenchmarkPublicContextAdapter(
            public_scenario=scenario,
            blinded_cell=cell,
            raw_memory_store=store,
        ),
        completion=completion,
        clock=lambda: _NOW,
    )
    assert completion.calls == 12
    final_path = output / "snapshots" / f"step-0012-{snapshot.snapshot_hash}.json"
    return _Run(root, final_path, store, scenario, cell, binding, plan, snapshot)


@pytest.fixture(scope="module")
def a4_claimed(
    tmp_path_factory: pytest.TempPathFactory,
    protocol: tuple[
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> _Run:
    return _run(
        tmp_path_factory.mktemp("recall-use-a4-claimed"),
        protocol=protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
        select_early=True,
        terminal_claim=True,
    )


def _gateway_receipts(
    run: _Run,
    root: Path,
    *,
    override_messages_step: int | None = None,
) -> tuple[
    list[SovereignRecallVerifiedGatewayExchange],
    SovereignRecallGatewayVerificationPolicy,
]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint = hashlib.sha256(public_der).hexdigest()
    ledger = TransportGatewayReplayLedger(root / "nonce-ledger")
    exchanges: list[SovereignRecallVerifiedGatewayExchange] = []
    for event in run.snapshot.events:
        registration = event.interaction.model_call_registrations[0]
        messages = event.interaction.messages
        if event.step_index == override_messages_step:
            messages = [dict(item) for item in messages]
            task = json.loads(messages[-1]["content"])
            task["recent_external_feedback"] = []
            messages[-1]["content"] = json.dumps(
                task,
                ensure_ascii=False,
                sort_keys=True,
            )
        request_bytes = canonical_json(
            {"model": event.interaction.model_name, "messages": messages}
        ).encode("utf-8")
        commitment = build_transport_gateway_request_commitment(
            request_bytes=request_bytes,
            request_id=f"recall-use-request-{event.step_index:02d}",
            provider_name="qwen",
            model_name=event.interaction.model_name,
            request_url=_URL,
            allowlisted_origins={_ORIGIN},
            nonce=hashlib.sha256(f"nonce-{root}-{event.step_index}".encode()).hexdigest(),
            issued_at_utc=_ISSUED,
            cell_id=run.binding.blinded_cell_id,
            trajectory_id=f"trajectory-v3:{run.binding.cell_binding_hash}",
            reservation_id=f"reservation-{event.step_index:02d}",
            reservation_hash=canonical_sha256({"reservation": event.step_index, "root": str(root)}),
            pre_call_id=registration.registration_id,
            pre_call_hash=registration.registration_hash,
        )
        response_capture = run.store.load_record(
            event.interaction.response_binding.record_relative_path,
            project_id=run.snapshot.seed.project_id,
        )
        reasoning_capture = run.store.load_record(
            event.interaction.reasoning_binding.record_relative_path,
            project_id=run.snapshot.seed.project_id,
        )
        response_body = canonical_json(
            {
                "id": f"provider-response-{event.step_index:02d}",
                "model": event.interaction.model_name,
                "choices": [
                    {
                        "message": {
                            "content": response_capture.blob_path.read_text(encoding="utf-8"),
                            "reasoning_content": reasoning_capture.blob_path.read_text(
                                encoding="utf-8"
                            ),
                        }
                    }
                ],
                "usage": {},
            }
        ).encode("utf-8")
        receipt = build_adaptive_transport_gateway_receipt(
            gateway_receipt_id=f"gateway-receipt-{event.step_index:02d}",
            request_commitment=commitment,
            transmitted_request_bytes=request_bytes,
            completed_at_utc=_COMPLETED,
            final_url=_URL,
            http_status_code=200,
            connected_ip="8.8.8.8",
            tls_protocol="TLSv1.3",
            response_body=response_body,
            gateway_build_sha256=_BUILD_HASH,
            gateway_source_sha256=_SOURCE_HASH,
            tls_peer_spki_sha256=hashlib.sha256(b"test-peer-spki").hexdigest(),
        )
        signature = private_key.sign(transport_gateway_receipt_signature_message(receipt))
        signed = build_signed_adaptive_transport_gateway_receipt(
            receipt=receipt,
            gateway_public_key_pem=public_pem,
            signature_base64=base64.b64encode(signature).decode("ascii"),
        )
        attestation = verify_adaptive_transport_gateway_receipt(
            signed,
            expected_request_commitment=commitment,
            trusted_public_key_sha256=fingerprint,
            trusted_gateway_build_sha256=_BUILD_HASH,
            trusted_gateway_source_sha256=_SOURCE_HASH,
            allowlisted_origins={_ORIGIN},
            now_utc=_NOW,
            replay_ledger=ledger,
        )
        exchanges.append(
            SovereignRecallVerifiedGatewayExchange.create(
                signed_receipt=signed,
                verified_attestation=attestation,
            )
        )
    policy = SovereignRecallGatewayVerificationPolicy(
        trusted_public_key_sha256=fingerprint,
        trusted_gateway_build_sha256=_BUILD_HASH,
        trusted_gateway_source_sha256=_SOURCE_HASH,
        allowlisted_origins={_ORIGIN},
        replay_ledger=ledger,
    )
    return exchanges, policy


def _audit(
    run: _Run,
    **kwargs: Any,
) -> SovereignRecallUseReceipt:
    return audit_sovereign_recall_use(
        run.final_path,
        public_scenario=run.scenario,
        blinded_cell=run.cell,
        cell_binding=run.binding,
        arm_runtime_plan=run.plan,
        raw_memory_store=run.store,
        **kwargs,
    )


def test_real_a4_chain_is_observable_but_diagnostic_transport_cannot_pass(
    a4_claimed: _Run,
) -> None:
    receipt = _audit(a4_claimed)

    assert receipt.controller_memory_transport_verified
    assert receipt.early_context_selected_outside_recent_window
    assert receipt.terminal_structured_consumption_verified
    assert receipt.observable_consumption_chain_verified
    assert not receipt.all_twelve_provider_actions_independently_signed
    assert not receipt.actual_sovereign_recall_use_verified
    assert receipt.scientific_result_generated is False
    assert any("diagnostic double" in item for item in receipt.findings_cn)


def test_all_exact_gates_produce_one_formal_actual_use_receipt(
    a4_claimed: _Run,
    tmp_path: Path,
) -> None:
    exchanges, policy = _gateway_receipts(a4_claimed, tmp_path)
    output = tmp_path / "sovereign-recall-use-receipt-v1.json"
    receipt = _audit(
        a4_claimed,
        verified_gateway_exchanges=exchanges,
        gateway_verification_policy=policy,
        output_path=output,
    )

    assert receipt.actual_sovereign_recall_use_verified
    assert receipt.formal_consumption_chain_verified
    assert len(receipt.gateway_evidence) == 12
    assert all(
        item.provider_response_model == "qwen3-test"
        and item.provider_response_model_utf8_sha256 == hashlib.sha256(b"qwen3-test").hexdigest()
        and item.provider_response_model_matches_interaction
        for item in receipt.gateway_evidence
    )
    assert receipt.causal_memory_benefit_verified is False
    assert receipt.benchmark_superiority_verified is False
    assert receipt.scientific_result_generated is False
    assert SovereignRecallUseReceipt.model_validate_json(output.read_bytes()) == receipt


def test_orphan_selection_blocks_actual_use(a4_claimed: _Run, tmp_path: Path) -> None:
    copied_run = tmp_path / "run"
    copied_vault = tmp_path / "vault"
    shutil.copytree(a4_claimed.root / "run", copied_run)
    shutil.copytree(a4_claimed.root / "vault", copied_vault)
    orphan = copied_run / "orphan" / "sovereign-recall-selection.json"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("{}", encoding="utf-8")
    clone = _Run(
        tmp_path,
        copied_run / "snapshots" / a4_claimed.final_path.name,
        RawMemoryStore(copied_vault),
        a4_claimed.scenario,
        a4_claimed.cell,
        a4_claimed.binding,
        a4_claimed.plan,
        a4_claimed.snapshot,
    )

    receipt = _audit(clone)
    assert receipt.orphan_selection_paths == ["orphan/sovereign-recall-selection.json"]
    assert not receipt.actual_sovereign_recall_use_verified


def test_early_context_not_selected_cannot_pass(
    protocol: tuple[
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        protocol=protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
        select_early=False,
        terminal_claim=False,
    )
    receipt = _audit(run)

    assert not receipt.early_context_selected_outside_recent_window
    assert not receipt.actual_sovereign_recall_use_verified


def test_feedback_absent_from_signed_request_is_rejected(
    a4_claimed: _Run,
    tmp_path: Path,
) -> None:
    exchanges, policy = _gateway_receipts(
        a4_claimed,
        tmp_path,
        override_messages_step=11,
    )
    with pytest.raises(
        SovereignRecallUseAuditError,
        match="gateway request messages differ",
    ):
        _audit(
            a4_claimed,
            verified_gateway_exchanges=exchanges,
            gateway_verification_policy=policy,
        )


def test_turn_twelve_without_structured_consumption_stays_red(
    protocol: tuple[
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        protocol=protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
        select_early=True,
        terminal_claim=False,
    )
    receipt = _audit(run)

    assert receipt.observable_consumption_chain_verified is False
    assert receipt.terminal_structured_consumption_verified is False
    assert any("memory_consumption_claims" in item for item in receipt.findings_cn)


def test_cross_cell_and_cross_arm_inputs_fail_closed(
    a4_claimed: _Run,
    protocol: tuple[
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> None:
    _, bundle, bridge = protocol
    other = next(
        item for item in bridge.cells if item.scenario_id != a4_claimed.binding.scenario_id
    )
    with pytest.raises(SovereignRecallUseAuditError, match="cross-cell"):
        audit_sovereign_recall_use(
            a4_claimed.final_path,
            public_scenario=a4_claimed.scenario,
            blinded_cell=a4_claimed.cell,
            cell_binding=other,
            arm_runtime_plan=a4_claimed.plan,
            raw_memory_store=a4_claimed.store,
        )
    del bundle
    with pytest.raises(SovereignRecallUseAuditError, match="cross-arm"):
        audit_sovereign_recall_use(
            a4_claimed.final_path,
            public_scenario=a4_claimed.scenario,
            blinded_cell=a4_claimed.cell,
            cell_binding=a4_claimed.binding,
            arm_runtime_plan=build_benchmark_arm_runtime_plan(
                AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY
            ),
            raw_memory_store=a4_claimed.store,
        )


def test_rehashed_selection_substitution_still_fails_raw_replay(
    a4_claimed: _Run,
    tmp_path: Path,
) -> None:
    copied_run = tmp_path / "run"
    copied_vault = tmp_path / "vault"
    shutil.copytree(a4_claimed.root / "run", copied_run)
    shutil.copytree(a4_claimed.root / "vault", copied_vault)
    selection_path = next(copied_run.rglob("sovereign-recall-selection.json"))
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    excerpt = payload["selected_excerpts"][0]
    excerpt["excerpt_text"] = "伪造但重新计算哈希的选择内容。"
    excerpt["excerpt_sha256"] = hashlib.sha256(excerpt["excerpt_text"].encode("utf-8")).hexdigest()
    excerpt["payload_character_count"] = len(excerpt["excerpt_text"])
    excerpt["excerpt_truncated"] = False
    forged = SovereignRecallSelection.create(
        **{key: value for key, value in payload.items() if key != "selection_hash"}
    )
    selection_path.write_bytes((canonical_json(forged) + "\n").encode("utf-8"))
    clone = _Run(
        tmp_path,
        copied_run / "snapshots" / a4_claimed.final_path.name,
        RawMemoryStore(copied_vault),
        a4_claimed.scenario,
        a4_claimed.cell,
        a4_claimed.binding,
        a4_claimed.plan,
        a4_claimed.snapshot,
    )

    with pytest.raises(
        (AdaptiveMemoryLoopAuditError, SovereignRecallUseAuditError),
        match="does not replay|selection action binding",
    ):
        _audit(clone)


def test_a3_genuine_trajectory_can_never_receive_a4_receipt(
    protocol: tuple[
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    tmp_path: Path,
) -> None:
    run = _run(
        tmp_path,
        protocol=protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
        select_early=False,
        terminal_claim=False,
    )
    receipt = _audit(run)

    assert receipt.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY
    assert not receipt.arm_is_adaptive_sovereign
    assert not receipt.actual_sovereign_recall_use_verified
    assert any("不是A4" in item for item in receipt.findings_cn)
