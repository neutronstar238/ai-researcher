from __future__ import annotations

import ast
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pytest

from autoresearch.kernel.contracts import canonical_json, canonical_sha256
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research import adaptive_loop_benchmark_cell_runner as runner_module
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_benchmark_arm_adapters import (
    BenchmarkArmRuntimePlan,
    build_benchmark_arm_runtime_plan,
)
from autoresearch.research.adaptive_loop_benchmark_cell_runner import (
    AdaptiveLoopBenchmarkCellRunError,
    BenchmarkCellRunArtifact,
    build_benchmark_cell_run_spec,
    load_benchmark_cell_run_artifact,
    run_diagnostic_benchmark_cell,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkExecutionBundle,
    AdaptiveLoopBenchmarkPublicScenario,
    write_adaptive_loop_benchmark_execution_protocol,
)
from autoresearch.research.adaptive_loop_benchmark_receipts import (
    AdaptiveLoopBenchmarkCellExecutionBinding,
    AdaptiveLoopBenchmarkReceiptBridge,
    TerminalEnvelope,
    write_adaptive_loop_benchmark_receipt_bridge_once,
    write_terminal_envelope_once,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveResearchSeed,
    ModelResearchActionDraft,
    ResearchOperator,
    create_adaptive_research_seed,
)

_REASONING = (
    "我先核对本轮唯一公开刺激、最近八轮反馈、当前分支与机械预算，再只从公开算子目录中选择"
    "一个动作。这个本地诊断不会调用网络、检索、临时Agent或Dreaming，也不会把动作内容当成"
    "科学证据。若目录只有一个固定算子就按隔离合同执行；自适应目录则选择拆分未知量，确保"
    "十二轮只验证组合、回执、上下文顺序和能力边界，不回答隐藏评分，也不声称创新或发表。"
) * 2


class _DiagnosticCompletion:
    diagnostic_only: Literal[True] = True

    def __init__(
        self,
        *,
        declared_provider: str = "diagnostic-local",
        declared_model: str = "diagnostic-double",
        stop_at: int | None = None,
        side_effect: Callable[[int], None] | None = None,
    ) -> None:
        self.calls = 0
        self.declared_provider = declared_provider
        self.declared_model = declared_model
        self.stop_at = stop_at
        self.side_effect = side_effect

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls += 1
        messages = kwargs["messages"]
        task = json.loads(messages[-1]["content"])
        step = int(task["step_index"])
        operators = list(task["available_operators"])
        if self.stop_at == step:
            operator = ResearchOperator.STOP_EXPLORATION
        elif len(operators) == 1:
            operator = ResearchOperator(operators[0])
        else:
            operator = ResearchOperator.DECOMPOSE_UNCERTAINTY
        proposal = ModelResearchActionDraft(
            step_index=step,
            branch_id=str(task["selected_branch"]["branch_id"]),
            operator=operator,
            action_title_cn=f"第{step}轮诊断动作保持内容边界",
            action_body_cn="仅拆分公开环境中的未知量，不生成研究结果或隐藏评分答案。",
            reason_for_choice_cn="该动作可验证循环组合而不触发任何外部科研能力。",
            expected_information_gain_cn="检查下一轮是否保留精确公开反馈与四臂能力隔离。",
        ).model_dump(mode="json")
        if self.side_effect is not None:
            self.side_effect(step)
        response = json.dumps(proposal, ensure_ascii=False, sort_keys=True)
        return LLMJsonCompletionResult(
            provider=self.declared_provider,
            base_url="https://diagnostic.invalid/v1",
            model_name=self.declared_model,
            endpoint="https://diagnostic.invalid/v1/chat/completions",
            response_text=response,
            parsed_json=proposal,
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            temperature=0.7,
            reasoning_text=_REASONING,
            reasoning_transport="dashscope_enable_thinking",
        )


@pytest.fixture(scope="module")
def runtime(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, AdaptiveLoopBenchmarkExecutionBundle, AdaptiveLoopBenchmarkReceiptBridge]:
    root = tmp_path_factory.mktemp("cell-runner-receipts")
    work = tmp_path_factory.mktemp("cell-runner-work")
    bundle = write_adaptive_loop_benchmark_execution_protocol(
        root,
        randomization_seed=27_132_026,
    )
    bridge = write_adaptive_loop_benchmark_receipt_bridge_once(root, bundle)
    return root, work, bundle, bridge


def _case(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    *,
    scenario_index: int,
    arm: AdaptiveLoopBenchmarkArm,
    suffix: str,
) -> tuple[
    Path,
    Path,
    AdaptiveLoopBenchmarkReceiptBridge,
    AdaptiveLoopBenchmarkPublicScenario,
    AdaptiveLoopBenchmarkCellExecutionBinding,
    BenchmarkArmRuntimePlan,
    RawMemoryStore,
    AdaptiveResearchSeed,
    AdaptiveLoopPolicy,
]:
    receipt_root, work_root, bundle, bridge = runtime
    scenario = bundle.protocol.public_scenarios[scenario_index]
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
    store = RawMemoryStore(work_root / f"vault-{suffix}")
    identity_suffix = canonical_sha256({"test_suffix": suffix})[:20]
    seed = create_adaptive_research_seed(
        loop_id=f"diag-loop-{identity_suffix}",
        project_id=f"diag_project_{identity_suffix}",
        objective_cn=scenario.objective_cn,
        scope_cn=scenario.scope_cn,
        raw_memory_store=store,
        captured_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    policy = AdaptiveLoopPolicy(
        policy_id="adaptive-loop-benchmark-diagnostic-v1",
        max_steps=12,
        max_model_calls=12,
        max_external_actions=12,
        max_temporary_agents=14,
        max_consecutive_stalls=4,
    )
    output = work_root / f"output-{suffix}"
    plan = build_benchmark_arm_runtime_plan(arm)
    assert cell.blinded_cell_id == binding.blinded_cell_id
    return (
        receipt_root,
        output,
        bridge,
        scenario,
        binding,
        plan,
        store,
        seed,
        policy,
    )


def _cell_from_case(
    bundle: AdaptiveLoopBenchmarkExecutionBundle,
    binding: AdaptiveLoopBenchmarkCellExecutionBinding,
) -> Any:
    return next(
        item
        for item in bundle.blinded_cells.cells
        if item.blinded_cell_id == binding.blinded_cell_id
    )


def _run_case(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    *,
    scenario_index: int,
    arm: AdaptiveLoopBenchmarkArm,
    suffix: str,
    completion: _DiagnosticCompletion,
) -> BenchmarkCellRunArtifact:
    (
        receipt_root,
        output,
        bridge,
        scenario,
        binding,
        plan,
        store,
        seed,
        policy,
    ) = _case(runtime, scenario_index=scenario_index, arm=arm, suffix=suffix)
    cell = _cell_from_case(runtime[2], binding)
    return run_diagnostic_benchmark_cell(
        receipt_root=receipt_root,
        output_dir=output,
        bridge=bridge,
        public_scenario=scenario,
        blinded_cell=cell,
        cell_binding=binding,
        arm_runtime_plan=plan,
        seed=seed,
        policy=policy,
        raw_memory_store=store,
        completion=completion,
    )


@pytest.fixture(scope="module")
def four_arm_artifacts(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> dict[AdaptiveLoopBenchmarkArm, BenchmarkCellRunArtifact]:
    artifacts: dict[AdaptiveLoopBenchmarkArm, BenchmarkCellRunArtifact] = {}
    for arm in AdaptiveLoopBenchmarkArm:
        fake_qwen = arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        completion = _DiagnosticCompletion(
            declared_provider="qwen" if fake_qwen else "diagnostic-local",
            declared_model="qwen3-max" if fake_qwen else "diagnostic-double",
        )
        artifact = _run_case(
            runtime,
            scenario_index=0,
            arm=arm,
            suffix=f"four-{arm.value}",
            completion=completion,
        )
        artifacts[arm] = artifact
        assert completion.calls == 12
    return artifacts


def test_four_arm_deterministic_diagnostic_smoke_is_never_a_scientific_result(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    four_arm_artifacts: dict[AdaptiveLoopBenchmarkArm, BenchmarkCellRunArtifact],
) -> None:
    for arm, artifact in four_arm_artifacts.items():
        assert artifact.arm_realization_audit.capability_matrix_realized is True
        assert artifact.formal_eligible is False
        assert artifact.provider_transport_anchor_count == 0
        assert artifact.runtime_evidence.transport_anchors == []
        assert artifact.terminal_envelope.formal_eligible is False
        assert artifact.scientific_result_generated is False
        assert artifact.scoring_not_executed is True
        assert artifact.actual_sovereign_recall_use_verified is False
        assert len(artifact.final_snapshot.events) == 12
        assert len(artifact.audit_raw_final_manifest.entries) == 61
        assert artifact.controller_visible_final_manifest.entry_count == 73
        artifact_path = (
            runtime[1] / f"output-four-{arm.value}" / ("benchmark-cell-run-artifact-v1.json")
        )
        assert load_benchmark_cell_run_artifact(artifact_path) == artifact
    sovereign = four_arm_artifacts[AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN]
    assert sovereign.declared_completion_providers == ["qwen"] * 12
    assert sovereign.declared_completion_models == ["qwen3-max"] * 12
    assert all(
        item.provider_name == "diagnostic_double" and not item.formal_eligible
        for item in sovereign.runtime_evidence.provider_attempts
    )
    serialized = canonical_json(sovereign)
    assert '"hidden_oracle"' not in serialized
    assert '"machine_oracle"' not in serialized


def test_cross_cell_cross_arm_and_private_scoring_input_fail_closed(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> None:
    (
        _,
        _,
        bridge,
        scenario,
        binding,
        plan,
        _,
        seed,
        policy,
    ) = _case(
        runtime,
        scenario_index=1,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
        suffix="cross",
    )
    cell = _cell_from_case(runtime[2], binding)
    other_binding = next(item for item in bridge.cells if item.scenario_id != binding.scenario_id)
    with pytest.raises(AdaptiveLoopBenchmarkCellRunError, match="different cells"):
        build_benchmark_cell_run_spec(
            bridge=bridge,
            public_scenario=scenario,
            blinded_cell=cell,
            cell_binding=other_binding,
            arm_runtime_plan=plan,
            seed=seed,
            policy=policy,
        )
    with pytest.raises(AdaptiveLoopBenchmarkCellRunError, match="runtime plan"):
        build_benchmark_cell_run_spec(
            bridge=bridge,
            public_scenario=scenario,
            blinded_cell=cell,
            cell_binding=binding,
            arm_runtime_plan=build_benchmark_arm_runtime_plan(
                AdaptiveLoopBenchmarkArm.FIXED_PIPELINE
            ),
            seed=seed,
            policy=policy,
        )
    with pytest.raises(AdaptiveLoopBenchmarkCellRunError):
        build_benchmark_cell_run_spec(
            bridge=bridge,
            public_scenario=runtime[2].runner_only_scoring,  # type: ignore[arg-type]
            blinded_cell=cell,
            cell_binding=binding,
            arm_runtime_plan=plan,
            seed=seed,
            policy=policy,
        )
    tree = ast.parse(Path(runner_module.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert "AdaptiveLoopBenchmarkHiddenOracleManifest" not in imported


def test_less_than_twelve_turns_has_no_terminal(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> None:
    completion = _DiagnosticCompletion(stop_at=5)
    terminal_paths_before = set(runtime[0].rglob("terminal-envelope-v3.json"))
    with pytest.raises(AdaptiveLoopBenchmarkCellRunError, match="twelve accepted turns"):
        _run_case(
            runtime,
            scenario_index=2,
            arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
            suffix="short",
            completion=completion,
        )
    assert completion.calls == 5
    assert set(runtime[0].rglob("terminal-envelope-v3.json")) == terminal_paths_before


@pytest.mark.parametrize("tamper_kind", ["context", "registration"])
def test_deleted_context_or_registration_prevents_receipt_closure(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    tamper_kind: str,
) -> None:
    scenario_index = 3 if tamper_kind == "context" else 4
    suffix = f"delete-{tamper_kind}"
    (
        receipt_root,
        output,
        bridge,
        scenario,
        binding,
        plan,
        store,
        seed,
        policy,
    ) = _case(
        runtime,
        scenario_index=scenario_index,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
        suffix=suffix,
    )

    def delete_after_context_capture(step: int) -> None:
        if step != 12:
            return
        if tamper_kind == "registration":
            registration = next(
                (output / "loop" / "action-call-registrations" / "step-0001").glob("*.json")
            )
            registration.unlink()
            return
        record_root = store.private_root / "projects" / seed.project_id / "records"
        for record_path in record_root.glob("*/*/*.json"):
            payload = json.loads(record_path.read_text(encoding="utf-8"))
            source_ref = payload["envelope"]["source_ref"]
            if "step:1:external-context:" in source_ref:
                record_path.unlink()
                return
        raise AssertionError("turn-one context record was not found")

    completion = _DiagnosticCompletion(side_effect=delete_after_context_capture)
    cell = _cell_from_case(runtime[2], binding)
    with pytest.raises(AdaptiveLoopBenchmarkCellRunError):
        run_diagnostic_benchmark_cell(
            receipt_root=receipt_root,
            output_dir=output,
            bridge=bridge,
            public_scenario=scenario,
            blinded_cell=cell,
            cell_binding=binding,
            arm_runtime_plan=plan,
            seed=seed,
            policy=policy,
            raw_memory_store=store,
            completion=completion,
        )
    assert completion.calls == 12


def test_red_arm_audit_blocks_runtime_receipts(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> None:
    suffix = "red-arm"
    output = runtime[1] / f"output-{suffix}"

    def add_orphan_selection(step: int) -> None:
        if step == 12:
            path = output / "loop" / "orphan" / "sovereign-recall-selection.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")

    completion = _DiagnosticCompletion(side_effect=add_orphan_selection)
    with pytest.raises(AdaptiveLoopBenchmarkCellRunError, match="arm realization audit"):
        _run_case(
            runtime,
            scenario_index=5,
            arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
            suffix=suffix,
            completion=completion,
        )
    binding = next(
        item
        for item in runtime[3].cells
        if item.scenario_id == runtime[2].protocol.public_scenarios[5].scenario_id
        and item.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY
    )
    assert not (
        runtime[0]
        / "runner-only"
        / "receipts"
        / "cells"
        / binding.blinded_cell_id
        / "terminal-envelope-v3.json"
    ).exists()


def test_budget_tamper_and_terminal_conflict_fail_closed(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    four_arm_artifacts: dict[AdaptiveLoopBenchmarkArm, BenchmarkCellRunArtifact],
) -> None:
    artifact = four_arm_artifacts[AdaptiveLoopBenchmarkArm.FIXED_PIPELINE]
    payload = artifact.model_dump(mode="json")
    payload["runtime_evidence"]["budget_ledger"]["settlements"].pop()
    with pytest.raises(ValueError, match="reservation"):
        BenchmarkCellRunArtifact.model_validate(payload)

    terminal = artifact.terminal_envelope
    write_terminal_envelope_once(runtime[0], runtime[3], terminal)
    terminal_payload = terminal.model_dump(mode="json", exclude={"terminal_hash"})
    terminal_payload["runtime_failure_recorded"] = not terminal.runtime_failure_recorded
    conflicting = TerminalEnvelope.create(**terminal_payload)
    with pytest.raises(Exception, match="differs from complete on-disk replay"):
        write_terminal_envelope_once(runtime[0], runtime[3], conflicting)


def test_unmarked_completion_is_rejected_before_model_call(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
) -> None:
    (
        receipt_root,
        output,
        bridge,
        scenario,
        binding,
        plan,
        store,
        seed,
        policy,
    ) = _case(
        runtime,
        scenario_index=6,
        arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
        suffix="unmarked",
    )
    cell = _cell_from_case(runtime[2], binding)

    def unmarked(**_: Any) -> LLMJsonCompletionResult:
        raise AssertionError("unmarked completion must not be called")

    with pytest.raises(AdaptiveLoopBenchmarkCellRunError, match="explicitly marked"):
        run_diagnostic_benchmark_cell(
            receipt_root=receipt_root,
            output_dir=output,
            bridge=bridge,
            public_scenario=scenario,
            blinded_cell=cell,
            cell_binding=binding,
            arm_runtime_plan=plan,
            seed=seed,
            policy=policy,
            raw_memory_store=store,
            completion=unmarked,  # type: ignore[arg-type]
        )


def test_spec_and_artifact_hashes_reject_recomputed_cross_identity(
    runtime: tuple[
        Path,
        Path,
        AdaptiveLoopBenchmarkExecutionBundle,
        AdaptiveLoopBenchmarkReceiptBridge,
    ],
    four_arm_artifacts: dict[AdaptiveLoopBenchmarkArm, BenchmarkCellRunArtifact],
) -> None:
    artifact = four_arm_artifacts[AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN]
    payload = artifact.model_dump(mode="json", exclude={"artifact_hash"})
    other = next(
        item
        for item in runtime[3].cells
        if item.cell_binding_hash != artifact.run_spec.cell_binding.cell_binding_hash
    )
    payload["run_spec"]["cell_binding"] = other.model_dump(mode="json")
    payload["artifact_hash"] = canonical_sha256(payload)
    with pytest.raises(ValueError):
        BenchmarkCellRunArtifact.model_validate(payload)
