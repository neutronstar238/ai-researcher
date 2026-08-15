from __future__ import annotations

import base64
import hashlib
import inspect
import itertools
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autoresearch.kernel.contracts import canonical_json, canonical_sha256
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.research import adaptive_loop_benchmark_live_runner as live_module
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_benchmark_arm_adapters import (
    BenchmarkArmRuntimePlan,
    build_benchmark_arm_runtime_plan,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkBlindedCell,
    AdaptiveLoopBenchmarkExecutionBundle,
    AdaptiveLoopBenchmarkPublicScenario,
    write_adaptive_loop_benchmark_execution_protocol,
)
from autoresearch.research.adaptive_loop_benchmark_live_runner import (
    AdaptiveLoopBenchmarkLiveRunError,
    FormalBenchmarkCellRunArtifact,
    FormalLiveCallOutcome,
    build_formal_gateway_trust_policy,
    load_formal_benchmark_cell_run_artifact,
    run_formal_benchmark_cell,
)
from autoresearch.research.adaptive_loop_benchmark_receipts import (
    AdaptiveLoopBenchmarkCellExecutionBinding,
    AdaptiveLoopBenchmarkReceiptBridge,
    write_adaptive_loop_benchmark_receipt_bridge_once,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveResearchSeed,
    ModelMemoryConsumptionClaim,
    ModelResearchActionDraft,
    ResearchOperator,
    create_adaptive_research_seed,
)
from autoresearch.research.adaptive_transport_gateway import (
    AdaptiveTransportGatewayReceipt,
    TransportGatewayReplayLedger,
    build_adaptive_transport_gateway_receipt,
    build_signed_adaptive_transport_gateway_receipt,
    extract_adaptive_transport_gateway_completion,
    transport_gateway_receipt_signature_message,
)
from autoresearch.research.adaptive_transport_gateway_worker import (
    AdaptiveTransportGatewayWorkerOutput,
    load_adaptive_transport_gateway_worker_request,
)

_NOW = datetime(2026, 8, 10, 5, 0, 0, tzinfo=timezone.utc)
_ORIGIN = "https://api.example.com"
_URL = f"{_ORIGIN}/v1/chat/completions"
_MODEL = "qwen3-test"
_BUILD_HASH = hashlib.sha256(b"formal-live-test-gateway-build").hexdigest()
_SOURCE_HASH = hashlib.sha256(b"formal-live-test-gateway-source").hexdigest()
_TLS_HASH = hashlib.sha256(b"formal-live-test-peer-spki").hexdigest()
_REASONING = (
    "我先核对本轮唯一公开刺激、最近八轮反馈、当前分支和机械预算，再从本轮真实开放的算子"
    "目录中自主选择信息增益最高的动作。召回内容只是带原始来源的线索，不等于正确性、因果"
    "收益、创新性或可发表性；只有它确实进入后续请求并改变终轮判断时，才填写结构化消费声明。"
) * 3


@dataclass(frozen=True)
class _Case:
    receipt_root: Path
    output_dir: Path
    bridge: AdaptiveLoopBenchmarkReceiptBridge
    scenario: AdaptiveLoopBenchmarkPublicScenario
    cell: AdaptiveLoopBenchmarkBlindedCell
    binding: AdaptiveLoopBenchmarkCellExecutionBinding
    plan: BenchmarkArmRuntimePlan
    store: RawMemoryStore
    seed: AdaptiveResearchSeed
    policy: AdaptiveLoopPolicy


class _SignedGatewayDouble:
    test_only = True

    def __init__(
        self,
        *,
        target_payload: str,
        use_dreaming: bool = False,
        terminal_claim: bool = False,
        http_status: int = 200,
        response_model: str | None = None,
        raise_before_output: bool = False,
    ) -> None:
        self.target_payload = target_payload
        self.use_dreaming = use_dreaming
        self.terminal_claim = terminal_claim
        self.http_status = http_status
        self.response_model = response_model
        self.raise_before_output = raise_before_output
        self.calls = 0
        self.request_payloads: list[dict[str, Any]] = []
        self._private_key = Ed25519PrivateKey.generate()
        public_key = self._private_key.public_key()
        self.public_pem = public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        public_der = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.public_fingerprint = hashlib.sha256(public_der).hexdigest()

    def __call__(self, canonical_worker_request: bytes) -> bytes:
        self.calls += 1
        if self.raise_before_output:
            raise RuntimeError("test gateway unavailable before signed output")
        worker_request = load_adaptive_transport_gateway_worker_request(canonical_worker_request)
        commitment = worker_request.request_commitment
        request_bytes = worker_request.request_bytes()
        request_payload = json.loads(request_bytes)
        assert isinstance(request_payload, dict)
        self.request_payloads.append(request_payload)
        if 200 <= self.http_status < 300:
            visible = self._action_json(request_payload)
            response_body = canonical_json(
                {
                    "id": f"formal-test-response-{self.calls:02d}",
                    "model": self.response_model or commitment.model_name,
                    "choices": [
                        {
                            "message": {
                                "content": visible,
                                "reasoning_content": _REASONING,
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 100 + self.calls,
                        "completion_tokens": 40,
                    },
                }
            ).encode("utf-8")
        else:
            response_body = canonical_json(
                {"error": {"code": "quota", "message": "test-only"}}
            ).encode("utf-8")
        receipt = build_adaptive_transport_gateway_receipt(
            gateway_receipt_id=f"formal-test-gateway-{self.calls:02d}",
            request_commitment=commitment,
            transmitted_request_bytes=request_bytes,
            completed_at_utc=commitment.issued_at_utc,
            final_url=commitment.request_url,
            http_status_code=self.http_status,
            connected_ip="8.8.8.8",
            tls_protocol="TLSv1.3",
            response_body=response_body,
            gateway_build_sha256=_BUILD_HASH,
            gateway_source_sha256=_SOURCE_HASH,
            tls_peer_spki_sha256=_TLS_HASH,
        )
        signature = self._private_key.sign(transport_gateway_receipt_signature_message(receipt))
        signed = build_signed_adaptive_transport_gateway_receipt(
            receipt=receipt,
            gateway_public_key_pem=self.public_pem,
            signature_base64=base64.b64encode(signature).decode("ascii"),
        )
        completion = extract_adaptive_transport_gateway_completion(
            response_body=response_body,
            http_status_code=self.http_status,
            expected_model_name=commitment.model_name,
        )
        payload: dict[str, Any] = {
            "schema_version": "adaptive-transport-gateway-worker-output-v2",
            "signed_receipt": signed.model_dump(mode="json"),
            "completion": (completion.model_dump(mode="json") if completion is not None else None),
        }
        payload["worker_output_hash"] = canonical_sha256(payload)
        output = AdaptiveTransportGatewayWorkerOutput.model_validate(payload)
        return canonical_json(output).encode("utf-8")

    def _action_json(self, request_payload: dict[str, Any]) -> str:
        messages = request_payload["messages"]
        task = json.loads(messages[-1]["content"])
        step = int(task["step_index"])
        available = [ResearchOperator(item) for item in task["available_operators"]]
        operator = (
            ResearchOperator.CONSOLIDATE_DREAMING
            if self.use_dreaming
            and step == 10
            and ResearchOperator.CONSOLIDATE_DREAMING in available
            else (available[0] if len(available) == 1 else ResearchOperator.DECOMPOSE_UNCERTAINTY)
        )
        title = f"第{step}轮自主缩减一个公开未知量"
        body = "区分公开观察、待核线索和未验证解释，不接触隐藏评分或生成科研结论。"
        if operator is ResearchOperator.CONSOLIDATE_DREAMING:
            title = "召回第一轮精确公开观察"
            body = f"从完整原始记录召回并核对这一早期观察：{self.target_payload}"
        claims: list[ModelMemoryConsumptionClaim] = []
        if step == 12 and self.terminal_claim:
            exposures = [
                exposure
                for feedback in task["recent_external_feedback"]
                for exposure in feedback.get("memory_exposures", [])
            ]
            matching = [item for item in exposures if item["excerpt_text"] == self.target_payload]
            assert matching, "turn 12 must receive the exact Dreaming exposure"
            exposure = matching[0]
            claims = [
                ModelMemoryConsumptionClaim(
                    schema_version="adaptive-model-memory-consumption-claim-v1",
                    dreaming_step_index=exposure["dreaming_step_index"],
                    selection_hash=exposure["selection_hash"],
                    record_id=exposure["record_id"],
                    payload_sha256=exposure["payload_sha256"],
                    excerpt_sha256=exposure["excerpt_sha256"],
                    fact_cn=exposure["excerpt_text"],
                    application_cn=(
                        "该早期公开观察改变了终轮证据取舍，因此保留其精确来源并拒绝被近期干扰改写。"
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
            expected_information_gain_cn="检验下一轮能否保留可追溯反馈并继续自主调整。",
            memory_consumption_claims=claims,
        )
        return json.dumps(
            proposal.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )


@pytest.fixture(scope="module")
def protocol(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, AdaptiveLoopBenchmarkExecutionBundle, AdaptiveLoopBenchmarkReceiptBridge]:
    receipt_root = tmp_path_factory.mktemp("formal-live-protocol")
    work_root = tmp_path_factory.mktemp("formal-live-work")
    bundle = write_adaptive_loop_benchmark_execution_protocol(
        receipt_root,
        randomization_seed=27_132_026,
    )
    bridge = write_adaptive_loop_benchmark_receipt_bridge_once(receipt_root, bundle)
    return receipt_root, work_root, bundle, bridge


def _case(
    protocol: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    *,
    arm: AdaptiveLoopBenchmarkArm,
    suffix: str,
) -> _Case:
    receipt_root, work_root, bundle, bridge = protocol
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
    identity = canonical_sha256({"formal_live_case": suffix})[:16]
    store = RawMemoryStore(work_root / f"vault-{suffix}")
    seed = create_adaptive_research_seed(
        loop_id=f"formal-live-{identity}",
        project_id=f"formal_live_{identity}",
        objective_cn=scenario.objective_cn,
        scope_cn=scenario.scope_cn,
        raw_memory_store=store,
        captured_at=_NOW,
    )
    return _Case(
        receipt_root=receipt_root,
        output_dir=work_root / f"output-{suffix}",
        bridge=bridge,
        scenario=scenario,
        cell=cell,
        binding=binding,
        plan=build_benchmark_arm_runtime_plan(arm),
        store=store,
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="formal-live-test-policy",
            max_steps=12,
            max_model_calls=12,
            max_external_actions=12,
            max_temporary_agents=14,
            max_consecutive_stalls=20,
        ),
    )


def _run(case: _Case, gateway: _SignedGatewayDouble) -> FormalBenchmarkCellRunArtifact:
    ledger = TransportGatewayReplayLedger(case.output_dir.parent / f"ledger-{case.seed.loop_id}")
    ids = itertools.count(1)
    nonces = itertools.count(1)
    return run_formal_benchmark_cell(
        receipt_root=case.receipt_root,
        output_dir=case.output_dir,
        bridge=case.bridge,
        public_scenario=case.scenario,
        blinded_cell=case.cell,
        cell_binding=case.binding,
        arm_runtime_plan=case.plan,
        seed=case.seed,
        policy=case.policy,
        gateway_trust_policy=build_formal_gateway_trust_policy(
            model_name=_MODEL,
            request_url=_URL,
            allowlisted_origins={_ORIGIN},
            trusted_gateway_public_key_sha256=gateway.public_fingerprint,
            trusted_gateway_build_sha256=_BUILD_HASH,
            trusted_gateway_source_sha256=_SOURCE_HASH,
        ),
        raw_memory_store=case.store,
        gateway_transport=gateway,
        replay_ledger=ledger,
        clock=lambda: _NOW,
        request_id_factory=lambda: f"formal-live-request-{next(ids):02d}",
        nonce_factory=lambda: hashlib.sha256(
            f"{case.seed.loop_id}:{next(nonces)}".encode()
        ).hexdigest(),
    )


def test_signed_gateway_runs_twelve_turn_non_memory_arm_without_scoring(
    protocol: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> None:
    case = _case(
        protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
        suffix="a3",
    )
    gateway = _SignedGatewayDouble(target_payload=case.scenario.stimuli[0].payload_cn)

    artifact = _run(case, gateway)

    assert gateway.calls == 12
    assert artifact.terminal is not None
    assert artifact.terminal.formal_eligible is False
    assert artifact.test_only_non_confirmatory
    assert artifact.eligibility_is_conditional_on_supplied_pin_provenance
    assert not artifact.python_api_verified_pin_provenance
    assert artifact.run_spec.gateway_trust_policy.test_only_false_is_external_provenance is False
    assert artifact.sovereign_recall_use_receipt is None
    assert len(artifact.call_evidence) == 12
    assert len(artifact.post_run_gateway_replays) == 12
    assert all(
        item.outcome is FormalLiveCallOutcome.PROVIDER_COMPLETION
        and item.external_gateway_signature_verified
        and item.request_messages_sha256 == canonical_sha256(item.request_messages)
        and item.worker_request.request_bytes()
        == canonical_json(gateway.request_payloads[item.call_index - 1]).encode("utf-8")
        and item.gateway_worker_stdout_sha256 is not None
        and not item.process_local_trace_used_for_formality
        and item.signed_receipt is not None
        and isinstance(item.signed_receipt.receipt, AdaptiveTransportGatewayReceipt)
        and item.signed_receipt.receipt.provider_response_model == _MODEL
        for item in artifact.call_evidence
    )
    assert artifact.scientific_result_generated is False
    assert artifact.scoring_not_executed
    assert (
        load_formal_benchmark_cell_run_artifact(
            case.output_dir / "formal-benchmark-cell-run-artifact-v1.json"
        )
        == artifact
    )


def test_a4_terminal_requires_observable_signed_actual_recall_use(
    protocol: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> None:
    case = _case(
        protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
        suffix="a4-actual",
    )
    gateway = _SignedGatewayDouble(
        target_payload=case.scenario.stimuli[0].payload_cn,
        use_dreaming=True,
        terminal_claim=True,
    )

    artifact = _run(case, gateway)

    assert artifact.terminal is not None
    assert artifact.sovereign_recall_use_receipt is not None
    assert artifact.sovereign_recall_use_receipt.actual_sovereign_recall_use_verified
    assert artifact.terminal.sovereign_recall_use_receipt_hash == (
        artifact.sovereign_recall_use_receipt.receipt_hash
    )
    assert artifact.terminal.actual_sovereign_recall_use_verified
    assert artifact.terminal.formal_eligible is False
    assert artifact.sovereign_recall_use_receipt.scientific_result_generated is False


def test_a4_capability_without_actual_use_is_typed_blocked_artifact(
    protocol: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> None:
    case = _case(
        protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
        suffix="a4-unused",
    )
    gateway = _SignedGatewayDouble(target_payload=case.scenario.stimuli[0].payload_cn)

    artifact = _run(case, gateway)

    assert gateway.calls == 12
    assert artifact.sovereign_recall_use_receipt is not None
    assert not artifact.sovereign_recall_use_receipt.actual_sovereign_recall_use_verified
    assert artifact.terminal is None
    assert artifact.runtime_failure_sha256 is not None
    assert not artifact.formal_eligible


@pytest.mark.parametrize("failure_kind", ["unsigned", "signed_http", "model_mismatch"])
def test_failed_gateway_attempt_is_charged_and_never_terminal(
    protocol: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    failure_kind: str,
) -> None:
    case = _case(
        protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
        suffix=f"failure-{failure_kind}",
    )
    gateway = _SignedGatewayDouble(
        target_payload=case.scenario.stimuli[0].payload_cn,
        http_status=429 if failure_kind == "signed_http" else 200,
        response_model="qwen3-wrong" if failure_kind == "model_mismatch" else None,
        raise_before_output=failure_kind == "unsigned",
    )

    artifact = _run(case, gateway)

    assert gateway.calls == 1
    assert artifact.terminal is None
    assert artifact.runtime_failure_sha256 is not None
    assert len(artifact.budget_ledger.reservations) == 1
    assert len(artifact.budget_ledger.settlements) == 1
    assert artifact.budget_ledger.declared_charged_total.main_model_requests == 1
    expected = (
        FormalLiveCallOutcome.SIGNED_HTTP_FAILURE
        if failure_kind == "signed_http"
        else FormalLiveCallOutcome.UNVERIFIED_GATEWAY_FAILURE
    )
    assert artifact.call_evidence[0].outcome is expected


def test_bridge_mismatch_blocks_before_gateway_invocation(
    protocol: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    tmp_path: Path,
) -> None:
    case = _case(
        protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
        suffix="bridge-block",
    )
    other_bundle = write_adaptive_loop_benchmark_execution_protocol(
        tmp_path / "other-protocol",
        randomization_seed=27_132_027,
    )
    other_bridge = write_adaptive_loop_benchmark_receipt_bridge_once(
        tmp_path / "other-protocol",
        other_bundle,
    )
    gateway = _SignedGatewayDouble(target_payload=case.scenario.stimuli[0].payload_cn)

    with pytest.raises(AdaptiveLoopBenchmarkLiveRunError, match="sealed disk bridge"):
        run_formal_benchmark_cell(
            receipt_root=case.receipt_root,
            output_dir=case.output_dir,
            bridge=other_bridge,
            public_scenario=case.scenario,
            blinded_cell=case.cell,
            cell_binding=case.binding,
            arm_runtime_plan=case.plan,
            seed=case.seed,
            policy=case.policy,
            gateway_trust_policy=build_formal_gateway_trust_policy(
                model_name=_MODEL,
                request_url=_URL,
                allowlisted_origins={_ORIGIN},
                trusted_gateway_public_key_sha256=gateway.public_fingerprint,
                trusted_gateway_build_sha256=_BUILD_HASH,
                trusted_gateway_source_sha256=_SOURCE_HASH,
            ),
            raw_memory_store=case.store,
            gateway_transport=gateway,
            replay_ledger=TransportGatewayReplayLedger(tmp_path / "unused-ledger"),
            clock=lambda: _NOW,
        )
    assert gateway.calls == 0


def test_source_hash_drift_blocks_before_gateway_invocation(
    protocol: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(
        protocol,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
        suffix="source-drift-block",
    )
    gateway = _SignedGatewayDouble(target_payload=case.scenario.stimuli[0].payload_cn)
    original = live_module._source_module_hashes
    checks = 0

    def _drifting_source_hashes() -> dict[str, str]:
        nonlocal checks
        checks += 1
        values = original()
        if checks >= 2:
            values = dict(values)
            values["adaptive_loop_benchmark_live_runner"] = "f" * 64
        return values

    monkeypatch.setattr(live_module, "_source_module_hashes", _drifting_source_hashes)

    with pytest.raises(AdaptiveLoopBenchmarkLiveRunError, match="before any signed-gateway"):
        _run(case, gateway)
    assert checks >= 2
    assert gateway.calls == 0


def test_production_runner_has_no_private_key_or_diagnostic_evidence_path() -> None:
    source = inspect.getsource(live_module)
    forbidden = (
        "Ed25519PrivateKey",
        "AUTORESEARCH_GATEWAY_PRIVATE_KEY",
        "run_llm_json_completion",
        "adaptive_loop_benchmark_cell_runner",
        "diagnostic_only",
        "hidden_oracle",
    )
    assert all(token not in source for token in forbidden)
    assert "process_local_trace_used_for_formality" in source
    assert "local_antireplay_ledger_is_independent_acceptance_evidence" in source
    assert "python_api_verified_pin_provenance" in source
    assert "test_only_false_is_external_provenance" in source
