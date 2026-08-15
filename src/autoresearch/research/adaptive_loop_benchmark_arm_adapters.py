"""Result-blind capability isolation for the four adaptive-loop benchmark arms.

The objects in this module are runner inputs and replay audits.  They never
call a model, expose a hidden oracle, score a cell, or synthesize a terminal
answer.  Raw records remain mandatory audit evidence for every arm; the
controller-visible sovereign-recall capability is the A4-only intervention.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    canonical_json,
    canonical_sha256,
)
from autoresearch.research.adaptive_loop_benchmark import (
    AdaptiveLoopBenchmarkArm,
    AdaptiveLoopBenchmarkArmSpec,
    build_adaptive_loop_benchmark_protocol,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveResearchBranch,
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ResearchOperator,
)
from autoresearch.research.adaptive_sovereign_recall import SovereignRecallSelection

_TURN_COUNT = 12
_FIXED_CYCLE = (
    ResearchOperator.DECOMPOSE_UNCERTAINTY,
    ResearchOperator.ADVERSARIAL_CRITIQUE,
    ResearchOperator.MUTATE_WORKFLOW_PROPOSAL,
)
FIXED_BENCHMARK_OPERATOR_SEQUENCE = _FIXED_CYCLE * 4
_ALWAYS_MECHANICAL_ADAPTIVE_OPERATORS = frozenset(
    {
        ResearchOperator.DECOMPOSE_UNCERTAINTY.value,
        ResearchOperator.ADVERSARIAL_CRITIQUE.value,
        ResearchOperator.MUTATE_WORKFLOW_PROPOSAL.value,
        ResearchOperator.ABANDON_BRANCH.value,
        ResearchOperator.STOP_EXPLORATION.value,
    }
)
_INITIAL_BRANCHING_OPERATORS = frozenset(
    {
        ResearchOperator.BRANCH_HYPOTHESIS.value,
        ResearchOperator.ANALOGICAL_TRANSFER.value,
        ResearchOperator.REFRAME_QUESTION.value,
    }
)
_SELECTION_FILENAME = "sovereign-recall-selection.json"


class AdaptiveLoopBenchmarkArmError(AdaptiveResearchLoopError):
    """Raised when an arm plan or realized trajectory crosses its capability boundary."""


class BenchmarkOperatorCatalogMode(str, Enum):
    FIXED_SINGLE_OPERATOR = "fixed_single_operator"
    OPEN_ADAPTIVE = "open_adaptive"


class BenchmarkArmRuntimePlanContent(KernelContract):
    """Frozen capability plan mechanically derived from the parent v1 arm spec."""

    schema_version: Literal["adaptive-loop-benchmark-arm-runtime-plan-v1"] = (
        "adaptive-loop-benchmark-arm-runtime-plan-v1"
    )
    parent_protocol_hash: Sha256
    arm: AdaptiveLoopBenchmarkArm
    parent_arm_spec: AdaptiveLoopBenchmarkArmSpec
    turn_count: Literal[12] = 12
    operator_catalog_mode: BenchmarkOperatorCatalogMode
    fixed_operator_sequence: list[ResearchOperator] = Field(max_length=_TURN_COUNT)
    next_operator_selected_by_model: bool
    operator_topology_fixed: bool
    branch_archive_enabled: bool
    dynamic_skills_enabled: bool
    temporary_dispatch_enabled: bool
    dreaming_enabled: bool
    controller_sovereign_raw_recall_enabled: bool
    audit_raw_receipts_retained: Literal[True] = True
    fixed_arm_autonomy_must_fail: bool
    non_intervention_configuration_hash: Sha256

    @model_validator(mode="after")
    def _validate_frozen_derivation(self) -> BenchmarkArmRuntimePlanContent:
        expected = _runtime_plan_payload(self.arm)
        actual = self.model_dump(mode="json", exclude={"plan_hash"})
        if actual != expected:
            raise ValueError("benchmark arm runtime plan differs from the frozen parent arm")
        return self


class BenchmarkArmRuntimePlan(BenchmarkArmRuntimePlanContent):
    plan_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> BenchmarkArmRuntimePlan:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"plan_hash"}))
        if self.plan_hash != expected:
            raise ValueError("benchmark arm runtime plan hash mismatch")
        return self

    @classmethod
    def create_for_arm(cls, arm: AdaptiveLoopBenchmarkArm) -> BenchmarkArmRuntimePlan:
        payload = _runtime_plan_payload(arm)
        return cls(**payload, plan_hash=canonical_sha256(payload))


@dataclass(frozen=True)
class BenchmarkArmAdapter:
    """Operator-catalog treatment passed through the generic loop deletion-only hook."""

    plan: BenchmarkArmRuntimePlan

    def __post_init__(self) -> None:
        try:
            validated = BenchmarkArmRuntimePlan.model_validate(self.plan.model_dump(mode="json"))
        except ValueError as exc:
            raise AdaptiveLoopBenchmarkArmError(
                "benchmark arm adapter received an invalid runtime plan"
            ) from exc
        object.__setattr__(self, "plan", validated)

    def __call__(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
        mechanically_available_operator_ids: Sequence[str],
    ) -> Sequence[str]:
        del seed, branch
        mechanical = list(mechanically_available_operator_ids)
        if self.plan.operator_catalog_mode is BenchmarkOperatorCatalogMode.FIXED_SINGLE_OPERATOR:
            step_index = snapshot.next_step_index
            if not 1 <= step_index <= self.plan.turn_count:
                raise AdaptiveLoopBenchmarkArmError(
                    "fixed benchmark arm received a step outside its frozen twelve turns"
                )
            scheduled = self.plan.fixed_operator_sequence[step_index - 1].value
            if scheduled not in mechanical:
                raise AdaptiveLoopBenchmarkArmError(
                    "fixed benchmark operator is not mechanically available"
                )
            return (scheduled,)
        if self.plan.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY:
            return tuple(
                item for item in mechanical if item != ResearchOperator.CONSOLIDATE_DREAMING.value
            )
        return tuple(mechanical)


class BenchmarkArmTurnRealization(KernelContract):
    step_index: int = Field(ge=1, le=_TURN_COUNT)
    available_operator_ids: list[str] = Field(max_length=32)
    selected_operator: ResearchOperator
    expected_fixed_operator: ResearchOperator | None = None
    selected_operator_was_exposed: bool
    branch_created: bool
    skill_message_ids: list[str] = Field(max_length=12)
    available_skill_ids: list[str] = Field(max_length=12)
    skill_projection_matches_task: bool
    temporary_batch_present: bool
    dreaming_operator_selected: bool
    dreaming_selection_artifact_refs: list[str] = Field(max_length=8)
    turn_matches_plan: bool
    findings_cn: list[str] = Field(default_factory=list, max_length=32)


class BenchmarkArmRealizationAuditContent(KernelContract):
    """Replay the effective capability matrix from messages, events, and artifacts."""

    schema_version: Literal["adaptive-loop-benchmark-arm-realization-audit-v1"] = (
        "adaptive-loop-benchmark-arm-realization-audit-v1"
    )
    parent_protocol_hash: Sha256
    arm: AdaptiveLoopBenchmarkArm
    plan_hash: Sha256
    snapshot_hash: Sha256
    turn_evidence: list[BenchmarkArmTurnRealization] = Field(max_length=_TURN_COUNT)
    observed_turn_count: int = Field(ge=0, le=_TURN_COUNT)
    final_branch_count: int = Field(ge=1)
    created_branch_count: int = Field(ge=0)
    skill_message_count: int = Field(ge=0)
    temporary_batch_count: int = Field(ge=0)
    dreaming_operator_count: int = Field(ge=0)
    sovereign_selection_artifact_count: int = Field(ge=0)
    orphan_sovereign_selection_paths: list[str] = Field(default_factory=list, max_length=64)
    capability_matrix_realized: bool
    actual_sovereign_recall_use_verified: Literal[False] = False
    scientific_result_generated: Literal[False] = False
    findings_cn: list[str] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def _validate_derived_counts(self) -> BenchmarkArmRealizationAuditContent:
        if self.observed_turn_count != len(self.turn_evidence):
            raise ValueError("benchmark arm observed-turn count mismatch")
        if self.created_branch_count != sum(item.branch_created for item in self.turn_evidence):
            raise ValueError("benchmark arm created-branch count mismatch")
        if self.skill_message_count != sum(
            len(item.skill_message_ids) for item in self.turn_evidence
        ):
            raise ValueError("benchmark arm skill-message count mismatch")
        if self.temporary_batch_count != sum(
            item.temporary_batch_present for item in self.turn_evidence
        ):
            raise ValueError("benchmark arm temporary-batch count mismatch")
        if self.dreaming_operator_count != sum(
            item.dreaming_operator_selected for item in self.turn_evidence
        ):
            raise ValueError("benchmark arm Dreaming count mismatch")
        expected_realized = (
            bool(self.turn_evidence)
            and all(item.turn_matches_plan for item in self.turn_evidence)
            and not self.findings_cn
        )
        if self.capability_matrix_realized != expected_realized:
            raise ValueError("benchmark arm realization verdict mismatch")
        return self


class BenchmarkArmRealizationAudit(BenchmarkArmRealizationAuditContent):
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> BenchmarkArmRealizationAudit:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))
        if self.audit_hash != expected:
            raise ValueError("benchmark arm realization audit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkArmRealizationAudit:
        content = BenchmarkArmRealizationAuditContent.model_validate(values)
        payload = content.model_dump(mode="json")
        return cls(**payload, audit_hash=canonical_sha256(payload))


def build_benchmark_arm_runtime_plan(
    arm: AdaptiveLoopBenchmarkArm,
) -> BenchmarkArmRuntimePlan:
    return BenchmarkArmRuntimePlan.create_for_arm(arm)


def build_benchmark_arm_runtime_plans() -> tuple[BenchmarkArmRuntimePlan, ...]:
    plans = tuple(build_benchmark_arm_runtime_plan(arm) for arm in AdaptiveLoopBenchmarkArm)
    validate_primary_contrast_runtime_plans(
        next(item for item in plans if item.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY),
        next(item for item in plans if item.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN),
    )
    return plans


def build_benchmark_arm_adapter(arm: AdaptiveLoopBenchmarkArm) -> BenchmarkArmAdapter:
    return BenchmarkArmAdapter(plan=build_benchmark_arm_runtime_plan(arm))


def validate_primary_contrast_runtime_plans(
    derived_only: BenchmarkArmRuntimePlan,
    sovereign: BenchmarkArmRuntimePlan,
) -> None:
    try:
        derived_only = BenchmarkArmRuntimePlan.model_validate(derived_only.model_dump(mode="json"))
        sovereign = BenchmarkArmRuntimePlan.model_validate(sovereign.model_dump(mode="json"))
    except ValueError as exc:
        raise AdaptiveLoopBenchmarkArmError(
            "primary contrast contains an invalid runtime plan"
        ) from exc
    if (
        derived_only.arm is not AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY
        or sovereign.arm is not AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
    ):
        raise AdaptiveLoopBenchmarkArmError("primary contrast plans use the wrong arms")
    if derived_only.non_intervention_configuration_hash != (
        sovereign.non_intervention_configuration_hash
    ):
        raise AdaptiveLoopBenchmarkArmError(
            "primary contrast differs outside sovereign recall and Dreaming"
        )
    differing_fields = {
        field
        for field in (
            "next_operator_selected_by_model",
            "operator_topology_fixed",
            "branch_archive_enabled",
            "dynamic_skills_enabled",
            "temporary_dispatch_enabled",
            "dreaming_enabled",
            "controller_sovereign_raw_recall_enabled",
            "audit_raw_receipts_retained",
            "fixed_operator_sequence",
            "operator_catalog_mode",
        )
        if getattr(derived_only, field) != getattr(sovereign, field)
    }
    if differing_fields != {
        "dreaming_enabled",
        "controller_sovereign_raw_recall_enabled",
    }:
        raise AdaptiveLoopBenchmarkArmError(
            "primary contrast capability matrix is not a single bundled intervention"
        )


def audit_benchmark_arm_realization(
    *,
    plan: BenchmarkArmRuntimePlan,
    snapshot: AdaptiveResearchLoopSnapshot,
    artifact_root: Path | str | None = None,
) -> BenchmarkArmRealizationAudit:
    try:
        plan = BenchmarkArmRuntimePlan.model_validate(plan.model_dump(mode="json"))
        snapshot = AdaptiveResearchLoopSnapshot.model_validate(snapshot.model_dump(mode="json"))
    except ValueError as exc:
        raise AdaptiveLoopBenchmarkArmError(
            "benchmark arm audit received an invalid content-addressed input"
        ) from exc
    root = Path(artifact_root).resolve() if artifact_root is not None else None
    evidence: list[BenchmarkArmTurnRealization] = []
    findings: list[str] = []
    referenced_selection_paths: set[Path] = set()
    referenced_selection_ids: set[str] = set()
    dreaming_exposed = False

    for event in snapshot.events:
        turn_findings: list[str] = []
        task, task_finding = _task_payload(event.interaction.messages)
        if task_finding is not None:
            turn_findings.append(task_finding)
        available = _available_operator_ids(task, turn_findings)
        available_set = set(available)
        selected = event.interaction.proposal.operator
        selected_exposed = selected.value in available_set
        if not selected_exposed:
            turn_findings.append("模型选择了本轮未暴露的算子。")
        skill_message_ids = _skill_message_ids(event.interaction.messages, turn_findings)
        available_skill_ids = _available_skill_ids(task, turn_findings)
        skill_projection_matches = skill_message_ids == available_skill_ids
        if not skill_projection_matches:
            turn_findings.append("Skill消息与任务中公开的Skill目录不一致。")

        expected_fixed: ResearchOperator | None = None
        if plan.operator_catalog_mode is BenchmarkOperatorCatalogMode.FIXED_SINGLE_OPERATOR:
            if event.step_index > len(plan.fixed_operator_sequence):
                turn_findings.append("固定臂超出冻结的十二轮序列。")
            else:
                expected_fixed = plan.fixed_operator_sequence[event.step_index - 1]
                if available != [expected_fixed.value]:
                    turn_findings.append("固定臂没有只暴露本轮冻结算子。")
                if selected is not expected_fixed:
                    turn_findings.append("固定臂执行了非冻结算子。")
        else:
            if not _ALWAYS_MECHANICAL_ADAPTIVE_OPERATORS.issubset(available_set):
                turn_findings.append("自适应臂删去了非干预的基础开放算子。")
            if event.step_index == 1:
                if not _INITIAL_BRANCHING_OPERATORS.issubset(available_set):
                    turn_findings.append("自适应臂首轮未开放冻结的分支能力。")
                if ResearchOperator.CONSULT_TEMPORARY_AGENTS.value not in available_set:
                    turn_findings.append("自适应臂首轮未开放临时Agent能力。")
            if ResearchOperator.CONSOLIDATE_DREAMING.value in available_set:
                dreaming_exposed = True
            if plan.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY and (
                ResearchOperator.CONSOLIDATE_DREAMING.value in available_set
            ):
                turn_findings.append("派生记忆臂暴露了Dreaming算子。")

        branch_created = event.created_branch_id is not None
        temporary_present = event.temporary_batch is not None
        dreaming_selected = selected is ResearchOperator.CONSOLIDATE_DREAMING
        selection_refs = [
            item for item in event.feedback.artifact_refs if _SELECTION_FILENAME in item
        ]
        if selection_refs and not dreaming_selected:
            turn_findings.append("非Dreaming事件绑定了主权召回选择制品。")
        referenced_selection_ids.update(selection_refs)
        if plan.arm in {
            AdaptiveLoopBenchmarkArm.FIXED_PIPELINE,
            AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP,
        }:
            if branch_created:
                turn_findings.append("固定拓扑臂创建了研究分支。")
            if temporary_present:
                turn_findings.append("固定拓扑臂调用了临时Agent。")
            if dreaming_selected or selection_refs:
                turn_findings.append("固定拓扑臂产生了Dreaming或主权召回制品。")
        if plan.arm is AdaptiveLoopBenchmarkArm.FIXED_PIPELINE and skill_message_ids:
            turn_findings.append("固定流水线臂注入了Skill消息。")
        if plan.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY and (
            dreaming_selected or selection_refs
        ):
            turn_findings.append("派生记忆臂产生了Dreaming或主权召回制品。")
        if plan.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN and dreaming_selected:
            replay_findings, replayed_paths = _replay_selection_artifact(
                event=event,
                artifact_root=root,
            )
            turn_findings.extend(replay_findings)
            referenced_selection_paths.update(replayed_paths)

        evidence.append(
            BenchmarkArmTurnRealization(
                step_index=event.step_index,
                available_operator_ids=available,
                selected_operator=selected,
                expected_fixed_operator=expected_fixed,
                selected_operator_was_exposed=selected_exposed,
                branch_created=branch_created,
                skill_message_ids=skill_message_ids,
                available_skill_ids=available_skill_ids,
                skill_projection_matches_task=skill_projection_matches,
                temporary_batch_present=temporary_present,
                dreaming_operator_selected=dreaming_selected,
                dreaming_selection_artifact_refs=selection_refs,
                turn_matches_plan=not turn_findings,
                findings_cn=turn_findings,
            )
        )
        findings.extend(f"第{event.step_index}轮：{item}" for item in turn_findings)

    orphan_paths: list[str] = []
    discovered_paths: set[Path] = set()
    if root is not None and root.exists():
        discovered_paths = {path.resolve() for path in root.rglob(_SELECTION_FILENAME)}
        orphan_paths = sorted(
            path.relative_to(root).as_posix()
            for path in discovered_paths - referenced_selection_paths
            if path.is_relative_to(root)
        )
        if orphan_paths:
            findings.append("运行目录含未由对应Dreaming事件绑定的主权召回制品。")

    if plan.operator_topology_fixed and len(evidence) != plan.turn_count:
        findings.append("固定拓扑臂没有完成冻结的十二轮能力序列。")
    if plan.arm in {
        AdaptiveLoopBenchmarkArm.FIXED_PIPELINE,
        AdaptiveLoopBenchmarkArm.LINEAR_MODEL_LOOP,
    }:
        fixed_root_shape = (
            len(snapshot.branches) == 1
            and snapshot.branches[0].branch_id == "branch_root"
            and snapshot.branches[0].parent_branch_id is None
            and snapshot.branches[0].created_step == 0
            and snapshot.branches[0].status.value == "active"
        )
        if not fixed_root_shape:
            findings.append("固定拓扑臂改变了初始研究分支结构或状态。")
    if plan.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_DERIVED_ONLY and (
        referenced_selection_ids or discovered_paths
    ):
        findings.append("派生记忆臂运行中存在任何主权召回选择制品。")
    if (
        plan.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        and evidence
        and (not dreaming_exposed)
    ):
        findings.append("主权记忆臂从未实际暴露Dreaming能力。")

    selection_ids = {item.removeprefix("artifact-path:") for item in referenced_selection_ids}
    if root is not None:
        selection_ids.update(
            path.relative_to(root).as_posix()
            for path in discovered_paths
            if path.is_relative_to(root)
        )
    realized = bool(evidence) and all(item.turn_matches_plan for item in evidence) and not findings
    return BenchmarkArmRealizationAudit.create(
        parent_protocol_hash=plan.parent_protocol_hash,
        arm=plan.arm,
        plan_hash=plan.plan_hash,
        snapshot_hash=snapshot.snapshot_hash,
        turn_evidence=evidence,
        observed_turn_count=len(evidence),
        final_branch_count=len(snapshot.branches),
        created_branch_count=sum(item.branch_created for item in evidence),
        skill_message_count=sum(len(item.skill_message_ids) for item in evidence),
        temporary_batch_count=sum(item.temporary_batch_present for item in evidence),
        dreaming_operator_count=sum(item.dreaming_operator_selected for item in evidence),
        sovereign_selection_artifact_count=len(selection_ids),
        orphan_sovereign_selection_paths=orphan_paths,
        capability_matrix_realized=realized,
        findings_cn=findings,
    )


def _runtime_plan_payload(arm: AdaptiveLoopBenchmarkArm) -> dict[str, Any]:
    protocol = build_adaptive_loop_benchmark_protocol()
    spec = next(item for item in protocol.arms if item.arm is arm)
    fixed = list(FIXED_BENCHMARK_OPERATOR_SEQUENCE) if spec.operator_topology_fixed else []
    configuration = spec.model_dump(mode="json")
    for intervention_field in (
        "arm",
        "append_only_raw_memory_available",
        "rebuildable_dreaming_available",
    ):
        configuration.pop(intervention_field)
    configuration.update(
        {
            "schema_version": "adaptive-loop-benchmark-non-intervention-config-v1",
            "turn_count": _TURN_COUNT,
            "operator_catalog_mode": (
                BenchmarkOperatorCatalogMode.FIXED_SINGLE_OPERATOR.value
                if spec.operator_topology_fixed
                else BenchmarkOperatorCatalogMode.OPEN_ADAPTIVE.value
            ),
            "fixed_operator_sequence": [item.value for item in fixed],
            "next_operator_selected_by_model": spec.next_operator_selected_by_model,
            "operator_topology_fixed": spec.operator_topology_fixed,
            "branch_archive_enabled": spec.branch_archive_available,
            "dynamic_skills_enabled": spec.dynamic_zero_or_more_skills,
            "temporary_dispatch_enabled": spec.main_agent_temporary_dispatch_available,
            "audit_raw_receipts_retained": True,
        }
    )
    return {
        "schema_version": "adaptive-loop-benchmark-arm-runtime-plan-v1",
        "parent_protocol_hash": protocol.protocol_hash,
        "arm": arm.value,
        "parent_arm_spec": spec.model_dump(mode="json"),
        "turn_count": _TURN_COUNT,
        "operator_catalog_mode": configuration["operator_catalog_mode"],
        "fixed_operator_sequence": configuration["fixed_operator_sequence"],
        "next_operator_selected_by_model": spec.next_operator_selected_by_model,
        "operator_topology_fixed": spec.operator_topology_fixed,
        "branch_archive_enabled": spec.branch_archive_available,
        "dynamic_skills_enabled": spec.dynamic_zero_or_more_skills,
        "temporary_dispatch_enabled": spec.main_agent_temporary_dispatch_available,
        "dreaming_enabled": spec.rebuildable_dreaming_available,
        "controller_sovereign_raw_recall_enabled": spec.append_only_raw_memory_available,
        "audit_raw_receipts_retained": True,
        "fixed_arm_autonomy_must_fail": not spec.next_operator_selected_by_model,
        "non_intervention_configuration_hash": canonical_sha256(configuration),
    }


def _task_payload(
    messages: Sequence[Mapping[Literal["role", "content"], str]],
) -> tuple[dict[str, Any], str | None]:
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
        return {}, "动作消息没有且仅有一个可重放任务载荷。"
    return candidates[0], None


def _available_operator_ids(task: Mapping[str, Any], findings: list[str]) -> list[str]:
    value = task.get("available_operators")
    if not isinstance(value, dict):
        findings.append("任务载荷缺少算子目录。")
        return []
    result = [str(item) for item in value]
    if len(result) != len(set(result)):
        findings.append("任务载荷重复了算子。")
    if any(item not in {operator.value for operator in ResearchOperator} for item in result):
        findings.append("任务载荷含未知算子。")
    return result


def _skill_message_ids(
    messages: Sequence[Mapping[Literal["role", "content"], str]],
    findings: list[str],
) -> list[str]:
    ids: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("context_kind") != (
            "selected_project_method_skill"
        ):
            continue
        skill_id = payload.get("skill_id")
        if not isinstance(skill_id, str) or not skill_id:
            findings.append("Skill消息缺少稳定ID。")
            continue
        ids.append(skill_id)
    if len(ids) != len(set(ids)):
        findings.append("同一轮重复注入了Skill消息。")
    return ids


def _available_skill_ids(task: Mapping[str, Any], findings: list[str]) -> list[str]:
    value = task.get("available_skill_ids")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        findings.append("任务载荷的Skill目录无效。")
        return []
    ids = [str(item) for item in value]
    if len(ids) != len(set(ids)):
        findings.append("任务载荷重复了Skill ID。")
    return ids


def _replay_selection_artifact(
    *,
    event: Any,
    artifact_root: Path | None,
) -> tuple[list[str], set[Path]]:
    findings: list[str] = []
    refs = list(event.feedback.artifact_refs)
    path_refs = [
        item.removeprefix("artifact-path:")
        for item in refs
        if item.startswith("artifact-path:") and item.endswith(_SELECTION_FILENAME)
    ]
    if len(path_refs) != 1:
        return ["Dreaming事件没有且仅有一个召回选择路径。"], set()
    if artifact_root is None:
        return ["Dreaming事件缺少可重放制品根目录。"], set()
    path = (artifact_root / Path(path_refs[0])).resolve()
    if not path.is_relative_to(artifact_root):
        return ["Dreaming召回选择路径逃逸运行目录。"], set()
    try:
        raw = path.read_bytes()
        selection = SovereignRecallSelection.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        return [f"Dreaming召回选择无法重放：{type(exc).__name__}。"], {path}
    if raw != (canonical_json(selection) + "\n").encode("utf-8"):
        findings.append("Dreaming召回选择不是规范化不可变JSON。")
    if (
        selection.loop_id != event.loop_id
        or selection.step_index != event.step_index
        or selection.branch_id != event.branch_id
        or selection.proposal_hash != canonical_sha256(event.interaction.proposal)
    ):
        findings.append("Dreaming召回选择没有绑定当前事件与动作。")
    if f"artifact:{selection.selection_hash}" not in refs:
        findings.append("Dreaming反馈没有绑定召回选择hash。")
    return findings, {path}


__all__ = [
    "AdaptiveLoopBenchmarkArmError",
    "BenchmarkArmAdapter",
    "BenchmarkArmRealizationAudit",
    "BenchmarkArmRuntimePlan",
    "BenchmarkArmTurnRealization",
    "BenchmarkOperatorCatalogMode",
    "FIXED_BENCHMARK_OPERATOR_SEQUENCE",
    "audit_benchmark_arm_realization",
    "build_benchmark_arm_adapter",
    "build_benchmark_arm_runtime_plan",
    "build_benchmark_arm_runtime_plans",
    "validate_primary_contrast_runtime_plans",
]
