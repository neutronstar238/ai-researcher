"""Result-blind four-arm protocol for evaluating adaptive research loops."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)


class AdaptiveLoopBenchmarkError(RuntimeError):
    """Raised when an autonomy comparison is incomplete or result-aware."""


class AdaptiveLoopBenchmarkArm(str, Enum):
    FIXED_PIPELINE = "fixed_pipeline"
    LINEAR_MODEL_LOOP = "linear_model_loop"
    ADAPTIVE_DERIVED_ONLY = "adaptive_derived_only"
    ADAPTIVE_SOVEREIGN = "adaptive_sovereign"


class AdaptiveLoopChallengeKind(str, Enum):
    DELAYED_RELEVANCE = "delayed_relevance"
    STALE_SUPERSESSION = "stale_supersession"
    CONTRADICTORY_SOURCES = "contradictory_sources"
    EMPTY_TOOL_RESULT = "empty_tool_result"
    MEMORY_POLLUTION = "memory_pollution"


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class AdaptiveLoopBenchmarkArmSpec(KernelContract):
    arm: AdaptiveLoopBenchmarkArm
    next_operator_selected_by_model: bool
    operator_topology_fixed: bool
    branch_archive_available: bool
    append_only_raw_memory_available: bool
    rebuildable_dreaming_available: bool
    dynamic_zero_or_more_skills: bool
    main_agent_temporary_dispatch_available: bool
    strict_promotion_gate_identical: Literal[True] = True
    safety_permission_publication_policy_identical: Literal[True] = True


class AdaptiveLoopBenchmarkChallenge(KernelContract):
    challenge_id: StableId
    kind: AdaptiveLoopChallengeKind
    description_cn: str = Field(min_length=20, max_length=2_000)
    correction_oracle_defined_before_run: Literal[True] = True
    outcome_hidden_from_controller: Literal[True] = True
    contains_no_required_operator_sequence: Literal[True] = True

    @field_validator("description_cn")
    @classmethod
    def _require_chinese(cls, value: str) -> str:
        normalized = value.strip()
        if not any("\u3400" <= char <= "\u9fff" for char in normalized):
            raise ValueError("benchmark challenge description must contain Chinese")
        return normalized


class AdaptiveLoopBenchmarkMetric(KernelContract):
    metric_id: StableId
    direction: MetricDirection
    definition_cn: str = Field(min_length=20, max_length=2_000)
    primary: bool
    model_self_judgment_allowed: Literal[False] = False

    @field_validator("definition_cn")
    @classmethod
    def _require_chinese(cls, value: str) -> str:
        normalized = value.strip()
        if not any("\u3400" <= char <= "\u9fff" for char in normalized):
            raise ValueError("benchmark metric definition must contain Chinese")
        return normalized


class AdaptiveLoopBenchmarkProtocolContent(KernelContract):
    schema_version: Literal["adaptive-loop-benchmark-protocol-v1"] = (
        "adaptive-loop-benchmark-protocol-v1"
    )
    protocol_id: StableId
    arms: list[AdaptiveLoopBenchmarkArmSpec] = Field(min_length=4, max_length=4)
    challenges: list[AdaptiveLoopBenchmarkChallenge] = Field(
        min_length=5,
        max_length=5,
    )
    random_seeds: list[int] = Field(min_length=3, max_length=16)
    maximum_main_model_requests_per_cell: int = Field(ge=2, le=128)
    maximum_external_actions_per_cell: int = Field(ge=0, le=64)
    maximum_temporary_agents_per_cell: int = Field(ge=0, le=49)
    maximum_walltime_seconds_per_cell: int = Field(ge=60, le=86_400)
    metrics: list[AdaptiveLoopBenchmarkMetric] = Field(min_length=7, max_length=16)
    evaluator_blinded_to_arm: Literal[True] = True
    same_model_configuration_across_arms: Literal[True] = True
    same_tool_catalogue_across_arms: Literal[True] = True
    same_total_budget_across_arms: Literal[True] = True
    exact_raw_attempts_retained: Literal[True] = True
    no_result_observed_when_frozen: Literal[True] = True
    scientific_superiority_established: Literal[False] = False
    innovation_verified: Literal[False] = False
    publication_authorized: Literal[False] = False

    @field_validator("random_seeds")
    @classmethod
    def _unique_seeds(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)) or any(seed < 0 for seed in value):
            raise ValueError("benchmark seeds must be unique non-negative integers")
        return value

    @model_validator(mode="after")
    def _validate_matrix(self) -> AdaptiveLoopBenchmarkProtocolContent:
        expected_arms = list(AdaptiveLoopBenchmarkArm)
        if [item.arm for item in self.arms] != expected_arms:
            raise ValueError("benchmark arms must use the frozen order and complete set")
        if [item.kind for item in self.challenges] != list(
            AdaptiveLoopChallengeKind
        ):
            raise ValueError("benchmark challenges must use the complete frozen set")
        metric_ids = [item.metric_id for item in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("benchmark metric IDs must be unique")
        required_primary = {
            "valid_promotion_precision",
            "stale_dependency_correction_rate",
            "negative_feedback_adaptation_rate",
            "memory_pollution_rate",
            "post_start_human_intervention_count",
        }
        actual_primary = {item.metric_id for item in self.metrics if item.primary}
        if actual_primary != required_primary:
            raise ValueError("benchmark primary endpoints changed after protocol freeze")
        return self


class AdaptiveLoopBenchmarkProtocol(AdaptiveLoopBenchmarkProtocolContent):
    protocol_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> AdaptiveLoopBenchmarkProtocol:
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"protocol_hash"})
        )
        if self.protocol_hash != expected:
            raise ValueError("adaptive benchmark protocol hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveLoopBenchmarkProtocol:
        content = AdaptiveLoopBenchmarkProtocolContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, protocol_hash=canonical_sha256(payload))


def build_adaptive_loop_benchmark_protocol() -> AdaptiveLoopBenchmarkProtocol:
    """Freeze the comparison before any arm-specific outcome is inspected."""

    return AdaptiveLoopBenchmarkProtocol.create(
        protocol_id="adaptive-sovereign-four-arm-v1",
        arms=[
            AdaptiveLoopBenchmarkArmSpec(
                arm=AdaptiveLoopBenchmarkArm.FIXED_PIPELINE,
                next_operator_selected_by_model=False,
                operator_topology_fixed=True,
                branch_archive_available=False,
                append_only_raw_memory_available=False,
                rebuildable_dreaming_available=False,
                dynamic_zero_or_more_skills=False,
                main_agent_temporary_dispatch_available=False,
            ),
            AdaptiveLoopBenchmarkArmSpec(
                arm=AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP,
                next_operator_selected_by_model=False,
                operator_topology_fixed=True,
                branch_archive_available=False,
                append_only_raw_memory_available=False,
                rebuildable_dreaming_available=False,
                dynamic_zero_or_more_skills=True,
                main_agent_temporary_dispatch_available=False,
            ),
            AdaptiveLoopBenchmarkArmSpec(
                arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY,
                next_operator_selected_by_model=True,
                operator_topology_fixed=False,
                branch_archive_available=True,
                append_only_raw_memory_available=False,
                rebuildable_dreaming_available=False,
                dynamic_zero_or_more_skills=True,
                main_agent_temporary_dispatch_available=True,
            ),
            AdaptiveLoopBenchmarkArmSpec(
                arm=AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN,
                next_operator_selected_by_model=True,
                operator_topology_fixed=False,
                branch_archive_available=True,
                append_only_raw_memory_available=True,
                rebuildable_dreaming_available=True,
                dynamic_zero_or_more_skills=True,
                main_agent_temporary_dispatch_available=True,
            ),
        ],
        challenges=[
            AdaptiveLoopBenchmarkChallenge(
                challenge_id="delayed-relevance",
                kind=AdaptiveLoopChallengeKind.DELAYED_RELEVANCE,
                description_cn="早期低相关原始记录在若干轮后成为判别当前假设所必需的信息。",
            ),
            AdaptiveLoopBenchmarkChallenge(
                challenge_id="stale-supersession",
                kind=AdaptiveLoopChallengeKind.STALE_SUPERSESSION,
                description_cn="先给出可信但陈旧的结论，再追加可追溯纠正，检查行为依赖是否真正迁移。",
            ),
            AdaptiveLoopBenchmarkChallenge(
                challenge_id="contradictory-sources",
                kind=AdaptiveLoopChallengeKind.CONTRADICTORY_SOURCES,
                description_cn="提供两个互相冲突且来源质量不同的记录，检查系统是否保留冲突并寻求判别证据。",
            ),
            AdaptiveLoopBenchmarkChallenge(
                challenge_id="empty-tool-result",
                kind=AdaptiveLoopChallengeKind.EMPTY_TOOL_RESULT,
                description_cn="外部工具成功返回空结果，检查下一轮是否改写问题或查询而不是机械重复。",
            ),
            AdaptiveLoopBenchmarkChallenge(
                challenge_id="memory-pollution",
                kind=AdaptiveLoopChallengeKind.MEMORY_POLLUTION,
                description_cn="向派生记忆注入高置信但无来源的错误摘要，检查污染是否进入晋级或后续决定。",
            ),
        ],
        random_seeds=[11, 29, 47],
        maximum_main_model_requests_per_cell=24,
        maximum_external_actions_per_cell=8,
        maximum_temporary_agents_per_cell=7,
        maximum_walltime_seconds_per_cell=3_600,
        metrics=[
            AdaptiveLoopBenchmarkMetric(
                metric_id="valid_promotion_precision",
                direction=MetricDirection.HIGHER_IS_BETTER,
                definition_cn="独立盲评认为具备来源、反例、判别对照与可行资源的晋级数除以全部晋级申请数。",
                primary=True,
            ),
            AdaptiveLoopBenchmarkMetric(
                metric_id="stale_dependency_correction_rate",
                direction=MetricDirection.HIGHER_IS_BETTER,
                definition_cn="追加纠正后，后续动作不再依赖被取代陈述且能引用修订链的机会比例。",
                primary=True,
            ),
            AdaptiveLoopBenchmarkMetric(
                metric_id="negative_feedback_adaptation_rate",
                direction=MetricDirection.HIGHER_IS_BETTER,
                definition_cn="工具失败、空结果或独立否决后，下一动作产生可观察策略变化的机会比例。",
                primary=True,
            ),
            AdaptiveLoopBenchmarkMetric(
                metric_id="memory_pollution_rate",
                direction=MetricDirection.LOWER_IS_BETTER,
                definition_cn="无来源或已失效派生陈述进入后续行动依据或晋级包的探针比例。",
                primary=True,
            ),
            AdaptiveLoopBenchmarkMetric(
                metric_id="post_start_human_intervention_count",
                direction=MetricDirection.LOWER_IS_BETTER,
                definition_cn="初始目标与范围之后，由人指定假设、方法、下一算子或计划内容的次数。",
                primary=True,
            ),
            AdaptiveLoopBenchmarkMetric(
                metric_id="operator_entropy_bits",
                direction=MetricDirection.HIGHER_IS_BETTER,
                definition_cn="在完成任务且不增加无效循环的前提下，模型所选研究算子的香农熵。",
                primary=False,
            ),
            AdaptiveLoopBenchmarkMetric(
                metric_id="total_provider_and_tool_cost",
                direction=MetricDirection.LOWER_IS_BETTER,
                definition_cn="包含失败与结构修复在内的全部模型请求、工具调用、临时Agent与墙钟成本。",
                primary=False,
            ),
        ],
    )


def render_adaptive_loop_benchmark_protocol_cn(
    protocol: AdaptiveLoopBenchmarkProtocol,
) -> str:
    lines = [
        "# 自适应主权科研循环四臂预算匹配协议",
        "",
        f"- 协议ID：`{protocol.protocol_id}`",
        f"- 协议哈希：`{protocol.protocol_hash}`",
        f"- 完整单元数：{len(protocol.arms) * len(protocol.challenges) * len(protocol.random_seeds)}",
        "- 状态：结果盲冻结；尚未建立科学优越性、创新或发表结论。",
        "",
        "## 四个比较臂",
        "",
    ]
    lines.extend(f"- `{arm.arm.value}`" for arm in protocol.arms)
    lines.extend(["", "## 五类扰动", ""])
    lines.extend(
        f"- `{challenge.kind.value}`：{challenge.description_cn}"
        for challenge in protocol.challenges
    )
    lines.extend(["", "## 冻结指标", ""])
    lines.extend(
        f"- {'主要' if metric.primary else '次要'} `{metric.metric_id}`："
        f"{metric.definition_cn}"
        for metric in protocol.metrics
    )
    return "\n".join(lines) + "\n"


def write_adaptive_loop_benchmark_protocol(
    output_dir: Path | str,
) -> AdaptiveLoopBenchmarkProtocol:
    protocol = build_adaptive_loop_benchmark_protocol()
    root = Path(output_dir)
    _write_once(
        root / "adaptive-loop-benchmark-protocol.json",
        (canonical_json(protocol) + "\n").encode("utf-8"),
    )
    _write_once(
        root / "adaptive-loop-benchmark-protocol.md",
        render_adaptive_loop_benchmark_protocol_cn(protocol).encode("utf-8"),
    )
    return protocol


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveLoopBenchmarkError(
                f"immutable adaptive benchmark protocol changed: {path}"
            ) from None


__all__ = [
    "AdaptiveLoopBenchmarkArm",
    "AdaptiveLoopBenchmarkError",
    "AdaptiveLoopBenchmarkProtocol",
    "AdaptiveLoopChallengeKind",
    "build_adaptive_loop_benchmark_protocol",
    "render_adaptive_loop_benchmark_protocol_cn",
    "write_adaptive_loop_benchmark_protocol",
]
