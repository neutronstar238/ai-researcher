"""Result-blind design and exact-power audit for the adaptive-loop benchmark."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    canonical_json,
    canonical_sha256,
)
from autoresearch.research.adaptive_loop_benchmark import (
    AdaptiveLoopBenchmarkError,
    AdaptiveLoopBenchmarkProtocol,
)
from autoresearch.research.search_policy_study import (
    exact_mcnemar_power,
    minimum_exact_mcnemar_sample_size,
)

_ALPHA = 0.05
_TARGET_POWER = 0.80
_SESOI_RISK_DIFFERENCE = 0.25
_UNFAVORABLE_DISCORDANCE_SCENARIOS = (0.00, 0.05, 0.10)
_RECOMMENDED_INDEPENDENT_SCENARIOS_PER_CHALLENGE = 12


class AdaptiveLoopBenchmarkPowerScenario(KernelContract):
    """Prospective exact-McNemar sensitivity for independent scenarios."""

    schema_version: Literal["adaptive-loop-benchmark-power-scenario-v2"] = (
        "adaptive-loop-benchmark-power-scenario-v2"
    )
    analysis_unit: Literal["independent_challenge_instance"] = (
        "independent_challenge_instance"
    )
    current_independent_unit_count: int = Field(ge=1)
    alpha: float = Field(gt=0.0, lt=1.0)
    target_power: float = Field(gt=0.0, lt=1.0)
    sesoi_risk_difference: float = Field(gt=0.0, lt=1.0)
    favorable_discordance_probability: float = Field(ge=0.0, le=1.0)
    unfavorable_discordance_probability: float = Field(ge=0.0, le=1.0)
    current_exact_power: float = Field(ge=0.0, le=1.0)
    required_independent_scenario_count: int = Field(ge=1)
    scenario_hash: Sha256

    @model_validator(mode="after")
    def _validate_exact_power(self) -> AdaptiveLoopBenchmarkPowerScenario:
        if self.alpha != _ALPHA or self.target_power != _TARGET_POWER:
            raise ValueError("benchmark power alpha or target changed")
        if self.sesoi_risk_difference != _SESOI_RISK_DIFFERENCE:
            raise ValueError("benchmark SESOI risk difference changed")
        if not math.isclose(
            self.favorable_discordance_probability
            - self.unfavorable_discordance_probability,
            self.sesoi_risk_difference,
            abs_tol=1e-12,
        ):
            raise ValueError("McNemar discordance does not match the SESOI")
        expected_power = exact_mcnemar_power(
            independent_unit_count=self.current_independent_unit_count,
            favorable_probability=self.favorable_discordance_probability,
            unfavorable_probability=self.unfavorable_discordance_probability,
            alpha=self.alpha,
        )
        if not math.isclose(self.current_exact_power, expected_power, abs_tol=1e-12):
            raise ValueError("McNemar exact power mismatch")
        required = minimum_exact_mcnemar_sample_size(
            favorable_probability=self.favorable_discordance_probability,
            unfavorable_probability=self.unfavorable_discordance_probability,
            alpha=self.alpha,
            target_power=self.target_power,
        )
        if self.required_independent_scenario_count != required:
            raise ValueError("McNemar required scenario count mismatch")
        expected_hash = canonical_sha256(
            self.model_dump(mode="json", exclude={"scenario_hash"})
        )
        if self.scenario_hash != expected_hash:
            raise ValueError("benchmark power scenario hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkPowerScenario:
        payload = {
            "schema_version": "adaptive-loop-benchmark-power-scenario-v2",
            "analysis_unit": "independent_challenge_instance",
            **values,
        }
        payload["scenario_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)


class AdaptiveLoopBenchmarkDesignAuditContent(KernelContract):
    """Mechanical interpretation of the result-blind v1 protocol."""

    schema_version: Literal["adaptive-loop-benchmark-design-audit-v2"] = (
        "adaptive-loop-benchmark-design-audit-v2"
    )
    protocol_hash: Sha256
    total_run_cell_count: int = Field(ge=1)
    arm_count: Literal[4] = 4
    challenge_template_count: Literal[5] = 5
    within_template_model_repeat_count: int = Field(ge=1)
    paired_run_block_count: int = Field(ge=1)
    independent_challenge_instance_count: Literal[5] = 5
    analysis_unit: Literal["independent_challenge_instance"] = (
        "independent_challenge_instance"
    )
    repeated_measure_role: Literal[
        "model_seeds_are_within_scenario_repeats_not_independent_units"
    ] = "model_seeds_are_within_scenario_repeats_not_independent_units"
    experimental_unit_cn: str = Field(min_length=20, max_length=2_000)
    blocking_and_contrast_cn: str = Field(min_length=20, max_length=2_000)
    primary_contrast: Literal[
        "adaptive_sovereign_minus_adaptive_derived_only"
    ] = "adaptive_sovereign_minus_adaptive_derived_only"
    confirmatory_primary_endpoint: Literal[
        "objectively_confirmed_terminal_success"
    ] = "objectively_confirmed_terminal_success"
    parent_v1_primary_metrics_reclassified_as: Literal[
        "secondary_descriptive_pilot_metrics"
    ] = "secondary_descriptive_pilot_metrics"
    primary_test: Literal["two_sided_exact_mcnemar"] = "two_sided_exact_mcnemar"
    primary_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    target_power: float = Field(default=0.80, gt=0.0, lt=1.0)
    sesoi_risk_difference: float = Field(default=0.25, gt=0.0, lt=1.0)
    v1_has_seeded_run_order: Literal[False] = False
    v1_has_exact_challenge_instances: Literal[False] = False
    v1_has_machine_readable_oracles: Literal[False] = False
    v1_has_zero_denominator_rules: Literal[False] = False
    v1_has_frozen_analysis_contract: Literal[False] = False
    per_challenge_inference_possible: Literal[False] = False
    pilot_execution_allowed_after_v2_freeze: Literal[True] = True
    confirmatory_superiority_claim_allowed: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False
    power_scenarios: list[AdaptiveLoopBenchmarkPowerScenario] = Field(
        min_length=3,
        max_length=3,
    )
    recommended_independent_scenarios_per_challenge: Literal[12] = 12
    recommended_confirmatory_independent_scenario_count: Literal[60] = 60
    recommended_confirmatory_cell_count: Literal[240] = 240
    confirmatory_cell_count_with_three_model_repeats: Literal[720] = 720
    findings_cn: list[str] = Field(min_length=7, max_length=20)

    @model_validator(mode="after")
    def _validate_design_counts(self) -> AdaptiveLoopBenchmarkDesignAuditContent:
        if self.primary_alpha != _ALPHA or self.target_power != _TARGET_POWER:
            raise ValueError("benchmark alpha or power target changed")
        if self.sesoi_risk_difference != _SESOI_RISK_DIFFERENCE:
            raise ValueError("benchmark SESOI changed")
        if self.paired_run_block_count != (
            self.challenge_template_count * self.within_template_model_repeat_count
        ):
            raise ValueError("paired run blocks do not match templates and repeats")
        if self.total_run_cell_count != self.paired_run_block_count * self.arm_count:
            raise ValueError("benchmark cell count does not match run blocks and arms")
        if self.independent_challenge_instance_count != self.challenge_template_count:
            raise ValueError("v1 has only one independent template per challenge kind")
        unfavorable = [
            item.unfavorable_discordance_probability for item in self.power_scenarios
        ]
        if unfavorable != list(_UNFAVORABLE_DISCORDANCE_SCENARIOS):
            raise ValueError("power discordance scenarios changed")
        if self.recommended_confirmatory_independent_scenario_count != (
            self.recommended_independent_scenarios_per_challenge
            * self.challenge_template_count
        ):
            raise ValueError("confirmatory scenario total does not preserve strata")
        if self.recommended_confirmatory_cell_count != (
            self.recommended_confirmatory_independent_scenario_count * self.arm_count
        ):
            raise ValueError("confirmatory cell total does not cover four arms")
        return self


class AdaptiveLoopBenchmarkDesignAudit(AdaptiveLoopBenchmarkDesignAuditContent):
    design_audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkDesignAudit:
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"design_audit_hash"})
        )
        if self.design_audit_hash != expected:
            raise ValueError("adaptive benchmark design audit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkDesignAudit:
        content = AdaptiveLoopBenchmarkDesignAuditContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, design_audit_hash=canonical_sha256(payload))


def audit_adaptive_loop_benchmark_design(
    protocol: AdaptiveLoopBenchmarkProtocol,
) -> AdaptiveLoopBenchmarkDesignAudit:
    """Audit experimental-unit and exact-power limits before any arm outcome."""

    if not protocol.no_result_observed_when_frozen:
        raise AdaptiveLoopBenchmarkError("design audit requires a result-blind protocol")
    arm_count = len(protocol.arms)
    repeat_count = len(protocol.random_seeds)
    run_blocks = len(protocol.challenges) * repeat_count
    independent_instances = len(protocol.challenges)
    scenarios = [
        _build_power_scenario(
            independent_unit_count=independent_instances,
            unfavorable_probability=unfavorable,
        )
        for unfavorable in _UNFAVORABLE_DISCORDANCE_SCENARIOS
    ]
    return AdaptiveLoopBenchmarkDesignAudit.create(
        protocol_hash=protocol.protocol_hash,
        total_run_cell_count=arm_count * run_blocks,
        within_template_model_repeat_count=repeat_count,
        paired_run_block_count=run_blocks,
        experimental_unit_cn=(
            "确认性分析的独立单位必须是预先生成、内容不同的挑战实例。v1中的三个seed"
            "只是同一挑战模板的模型重复测量；同一运行内的动作、临时Agent、探针和三个"
            "seed都不能扩充可外推的独立任务数。"
        ),
        blocking_and_contrast_cn=(
            "每个独立挑战实例构成区组并运行全部四臂。唯一确认性主对比是自适应主权记忆"
            "功能包相对于自适应派生记忆功能包；它同时改变原始记忆与Dreaming，因此"
            "不能分别声称单组件或交互作用的因果效果。"
        ),
        power_scenarios=scenarios,
        findings_cn=[
            "v1的六十个cell来自四臂、五个挑战描述和三个seed，不是六十个独立科研任务。",
            "seed是同一模板内重复，当前可外推的独立挑战实例最多只有五个；双侧精确McNemar在五个单位上没有形成显著结果的可能。",
            "父协议的五个primary没有唯一主对比、客观终态成功定义或多重性顺序，必须降为pilot描述指标。",
            "零晋级会让precision分母为零；v2必须以oracle确认的终态成功替代可被不行动博弈的空分母指标。",
            "v1没有逐实例刺激、注入时点、机器oracle、随机次序、同源工具replay、缺失处理或冻结分析程序。",
            "当前六十cell只能在v2 execution freeze后作为工程pilot，报告失败、区间与成本，不做p值优越性结论。",
            "在风险差0.25的三个前瞻discordance情景中，达到80%功效需要31至60个独立场景；保守采用每类十二个、总计六十个。",
            "确认性最窄矩阵是六十个独立场景乘四臂等于二百四十cell；若每场景保留三个模型重复则为七百二十cell，但分析n仍是六十。",
            "在完整runner、盲法、oracle与独立场景面板形成前，科学优越、创新成立与发表授权全部保持false。",
        ],
    )


def render_adaptive_loop_benchmark_design_audit_cn(
    audit: AdaptiveLoopBenchmarkDesignAudit,
) -> str:
    lines = [
        "# 自适应科研四臂协议的结果前设计与功效审计",
        "",
        f"- 父协议哈希：`{audit.protocol_hash}`",
        f"- 审计哈希：`{audit.design_audit_hash}`",
        f"- v1运行cell：{audit.total_run_cell_count}",
        f"- 配对运行区组：{audit.paired_run_block_count}",
        f"- 独立挑战实例：{audit.independent_challenge_instance_count}",
        "- 定位：v1只允许工程pilot；不允许确认性优越、创新或发表结论。",
        "",
        "## 实验单位与主对比",
        "",
        audit.experimental_unit_cn,
        "",
        audit.blocking_and_contrast_cn,
        "",
        "## 双侧精确McNemar前瞻敏感性",
        "",
        "| 不利discordance概率 | 当前5实例功效 | 80%功效所需独立实例 |",
        "|---:|---:|---:|",
    ]
    lines.extend(
        "| "
        f"{scenario.unfavorable_discordance_probability:.2f} | "
        f"{scenario.current_exact_power:.3f} | "
        f"{scenario.required_independent_scenario_count} |"
        for scenario in audit.power_scenarios
    )
    lines.extend(
        [
            "",
            "## 结果前建议矩阵",
            "",
            f"- 每类独立实例：{audit.recommended_independent_scenarios_per_challenge}",
            f"- 独立实例总数：{audit.recommended_confirmatory_independent_scenario_count}",
            f"- 单次模型运行cell：{audit.recommended_confirmatory_cell_count}",
            f"- 三次模型重复cell：{audit.confirmatory_cell_count_with_three_model_repeats}",
            "",
            "## 结果前发现",
            "",
        ]
    )
    lines.extend(f"- {finding}" for finding in audit.findings_cn)
    return "\n".join(lines) + "\n"


def write_adaptive_loop_benchmark_design_audit(
    protocol: AdaptiveLoopBenchmarkProtocol,
    output_dir: Path | str,
) -> AdaptiveLoopBenchmarkDesignAudit:
    audit = audit_adaptive_loop_benchmark_design(protocol)
    root = Path(output_dir)
    _write_once(
        root / "adaptive-loop-benchmark-design-audit-v2.json",
        (canonical_json(audit) + "\n").encode("utf-8"),
    )
    _write_once(
        root / "adaptive-loop-benchmark-design-audit-v2.md",
        render_adaptive_loop_benchmark_design_audit_cn(audit).encode("utf-8"),
    )
    return audit


def _build_power_scenario(
    *,
    independent_unit_count: int,
    unfavorable_probability: float,
) -> AdaptiveLoopBenchmarkPowerScenario:
    favorable_probability = unfavorable_probability + _SESOI_RISK_DIFFERENCE
    values = {
        "current_independent_unit_count": independent_unit_count,
        "alpha": _ALPHA,
        "target_power": _TARGET_POWER,
        "sesoi_risk_difference": _SESOI_RISK_DIFFERENCE,
        "favorable_discordance_probability": favorable_probability,
        "unfavorable_discordance_probability": unfavorable_probability,
        "current_exact_power": exact_mcnemar_power(
            independent_unit_count=independent_unit_count,
            favorable_probability=favorable_probability,
            unfavorable_probability=unfavorable_probability,
            alpha=_ALPHA,
        ),
        "required_independent_scenario_count": minimum_exact_mcnemar_sample_size(
            favorable_probability=favorable_probability,
            unfavorable_probability=unfavorable_probability,
            alpha=_ALPHA,
            target_power=_TARGET_POWER,
        ),
    }
    return AdaptiveLoopBenchmarkPowerScenario.create(**values)


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveLoopBenchmarkError(
                f"immutable adaptive benchmark design audit changed: {path}"
            ) from None


__all__ = [
    "AdaptiveLoopBenchmarkDesignAudit",
    "AdaptiveLoopBenchmarkPowerScenario",
    "audit_adaptive_loop_benchmark_design",
    "render_adaptive_loop_benchmark_design_audit_cn",
    "write_adaptive_loop_benchmark_design_audit",
]
