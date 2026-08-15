"""Run and interpret the bounded preliminary experiment required by the contest.

The competition's ``科学假设与研究计划`` is not an empty preregistration: its
``实验结果`` section must contain a derivation or an actual execution that establishes
feasibility in a limited range.  This module performs the deliberately narrow actual
execution before the final plan is authored.

The run is a baseline/harness feasibility probe, not a test of the proposed treatment.
It opens only public development cells, uses the pinned network-disabled official
runner, and selects at most one target system per data type.  Qwen then writes the
Chinese interpretation from exact machine evidence lines.  The orchestrator supplies
no scientific prose and a deterministic guard prevents Qwen from inventing numbers or
claiming that the prospective intervention was measured.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import record_model_authorship_receipt
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.official_development_search import (
    OfficialCellResult,
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
    build_official_cell_specs,
    execute_official_stage,
    freeze_official_identity,
)
from autoresearch.competition.system_plan_ideation import ResearchDirectionCandidate
from autoresearch.competition.system_plan_prospective_atoms import (
    ComponentExperimentBindingV2,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.schemas import file_hash

_ARTIFACT_NAME = "system-plan-preexperiment.json"
_SELECTED_SPECS_NAME = "preexperiment-selected-specs.json"
_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


class SystemPlanPreexperimentError(RuntimeError):
    """Raised when the real preliminary execution or its interpretation is invalid."""


def _is_cjk_ideograph(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2EBEF
        or 0x2F800 <= codepoint <= 0x2FA1F
        or 0x30000 <= codepoint <= 0x323AF
    )


def _missing_required_chinese_prose(fields: Mapping[str, str]) -> tuple[str, ...]:
    """Reject blank or non-Chinese prose without imposing stylistic length quotas."""

    return tuple(
        name
        for name, value in fields.items()
        if not (text := str(value).strip())
        or not any(_is_cjk_ideograph(char) for char in text)
    )


class PreexperimentSystemSelection(StrictFrozenModel):
    """One result-blind target chosen from the selected direction and public panel."""

    system_name: str = Field(min_length=1)
    data_type: Literal["ode", "pde"]
    selection_rule: Literal["first_selected_direction_target_per_data_type"] = (
        "first_selected_direction_target_per_data_type"
    )


class PreexperimentRawResultEvidence(StrictFrozenModel):
    """Exact on-disk runner result and its public, Chinese evidence projection."""

    spec: OfficialCellSpec
    result: OfficialCellResult
    raw_result_relative_path: str = Field(min_length=1)
    raw_result_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_line_zh: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_identity(self) -> PreexperimentRawResultEvidence:
        for field in (
            "attempt_id",
            "method_kind",
            "candidate_id",
            "stage",
            "system_name",
            "data_type",
            "condition",
            "seed",
        ):
            if getattr(self.spec, field) != getattr(self.result, field):
                raise SystemPlanPreexperimentError(
                    f"预实验 spec/result 身份字段不一致：{field}"
                )
        expected_line = _evidence_line(self.result)
        if self.evidence_line_zh != expected_line:
            raise SystemPlanPreexperimentError("预实验中文证据行不是结果的机械投影")
        return self


class PreexperimentInterpretation(StrictFrozenModel):
    """Chinese prose authored by Qwen from the exact preliminary result bytes."""

    schema_version: Literal["system-plan-preexperiment-interpretation-v1"] = (
        "system-plan-preexperiment-interpretation-v1"
    )
    evidence_lines_zh: tuple[str, ...] = Field(min_length=1)
    feasibility_status: Literal["limited_scope_supported", "not_supported"]
    feasibility_conclusion_zh: str = Field(min_length=1)
    limitations_zh: str = Field(min_length=1)
    plan_results_zh: str = Field(min_length=1)
    treatment_effect_measured: Literal[False] = False
    full_experiment_completed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_language_and_scope(self) -> PreexperimentInterpretation:
        prose = {
            "feasibility_conclusion_zh": self.feasibility_conclusion_zh,
            "limitations_zh": self.limitations_zh,
            "plan_results_zh": self.plan_results_zh,
        }
        failures = _missing_required_chinese_prose(prose)
        failures += non_chinese_prose_fields(
            prose,
            minimum_ratio=0.5,
        )
        if failures:
            raise SystemPlanPreexperimentError(
                f"预实验解释必须使用中文技术散文：{list(failures)}"
            )
        result_text = self.plan_results_zh
        if "预实验" not in result_text:
            raise SystemPlanPreexperimentError("计划结果段必须明确标注为预实验")
        if "未测量" not in result_text or not any(
            marker in result_text for marker in ("处理效应", "干预效应", "新方法效果")
        ):
            raise SystemPlanPreexperimentError(
                "计划结果段必须明确声明未测量拟议干预的处理效应"
            )
        return self


class SystemPlanPreexperimentArtifact(StrictFrozenModel):
    """Actual sandbox execution, raw cells, and exact Qwen-authored plan result."""

    schema_version: Literal["system-plan-preexperiment-artifact-v1"] = (
        "system-plan-preexperiment-artifact-v1"
    )
    lineage_id: str = Field(min_length=1)
    selected_direction_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_experiment_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: OfficialDevelopmentIdentity
    selected_systems: tuple[PreexperimentSystemSelection, ...] = Field(
        min_length=1, max_length=2
    )
    selected_seed: int
    selected_condition: Literal["clean"] = "clean"
    cell_evidence: tuple[PreexperimentRawResultEvidence, ...] = Field(min_length=1)
    interpretation: PreexperimentInterpretation
    interpretation_receipt_relative_path: str = Field(min_length=1)
    interpretation_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_name: str = Field(min_length=1)
    authoring_attempts: int = Field(ge=1, le=3)
    all_cells_succeeded: bool
    limited_feasibility_supported: bool
    sandbox_network_disabled: Literal[True] = True
    preliminary_only: Literal[True] = True
    treatment_effect_measured: Literal[False] = False
    full_experiment_completed: Literal[False] = False
    scientific_hypothesis_validated: Literal[False] = False
    publication_ready: Literal[False] = False
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_artifact(self) -> SystemPlanPreexperimentArtifact:
        expected_all = all(
            item.result.status == "succeeded" for item in self.cell_evidence
        )
        if self.all_cells_succeeded != expected_all:
            raise SystemPlanPreexperimentError("预实验成功门与逐单元状态不一致")
        expected_limited = any(
            item.result.status == "succeeded" for item in self.cell_evidence
        )
        if self.limited_feasibility_supported != expected_limited:
            raise SystemPlanPreexperimentError("有限可行性门必须由至少一个真实成功单元触发")
        expected_status = (
            "limited_scope_supported" if expected_limited else "not_supported"
        )
        if self.interpretation.feasibility_status != expected_status:
            raise SystemPlanPreexperimentError("Qwen 可行性结论与机械成功门冲突")
        conclusion = self.interpretation.feasibility_conclusion_zh
        result_text = self.interpretation.plan_results_zh
        if expected_limited:
            if "有限" not in conclusion or not any(
                marker in conclusion for marker in ("可运行", "可行")
            ):
                raise SystemPlanPreexperimentError("成功预实验必须只作有限可行性结论")
        elif not any(marker in conclusion for marker in ("未建立", "不支持", "未能")):
            raise SystemPlanPreexperimentError("全失败预实验必须明确写明可行性未建立")
        if not expected_limited and not any(
            marker in result_text for marker in ("未建立", "不支持", "未能")
        ):
            raise SystemPlanPreexperimentError("全失败计划结果段不得暗示可行性成立")
        evidence_lines = tuple(item.evidence_line_zh for item in self.cell_evidence)
        if self.interpretation.evidence_lines_zh != evidence_lines:
            raise SystemPlanPreexperimentError("Qwen 未逐字继承全部预实验证据行")
        _guard_interpretation_numbers(
            text=self.interpretation.plan_results_zh,
            evidence_lines=evidence_lines,
        )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected:
            raise SystemPlanPreexperimentError("预实验 artifact 哈希不符")
        return self

    def plan_context(self) -> dict[str, Any]:
        """Return the exact minimum context the final Qwen plan must inherit."""

        return {
            "schema_version": "system-plan-preexperiment-plan-context-v1",
            "artifact_hash": self.artifact_hash,
            "selected_direction_hash": self.selected_direction_hash,
            "component_experiment_binding_hash": (
                self.component_experiment_binding_hash
            ),
            "evidence_lines_zh": list(self.interpretation.evidence_lines_zh),
            "feasibility_status": self.interpretation.feasibility_status,
            "feasibility_conclusion_zh": (
                self.interpretation.feasibility_conclusion_zh
            ),
            "limitations_zh": self.interpretation.limitations_zh,
            "plan_results_zh": self.interpretation.plan_results_zh,
            "preliminary_only": True,
            "treatment_effect_measured": False,
            "full_experiment_completed": False,
        }


class _PreexperimentInterpretationResponse(PreexperimentInterpretation):
    """Strict provider response shape."""


_PREEXPERIMENT_MACHINE_FIELDS = (
    "schema_version",
    "evidence_lines_zh",
    "feasibility_status",
    "treatment_effect_measured",
    "full_experiment_completed",
)


def _preexperiment_response_schema() -> dict[str, Any]:
    """Expose only Qwen-authored interpretation prose to the provider."""

    schema: dict[str, Any] = json.loads(
        json.dumps(_PreexperimentInterpretationResponse.model_json_schema())
    )
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise SystemPlanPreexperimentError("预实验解释 schema 不是可投影对象")
    for field_name in _PREEXPERIMENT_MACHINE_FIELDS:
        properties.pop(field_name, None)
    schema["required"] = [
        field_name
        for field_name in required
        if field_name not in _PREEXPERIMENT_MACHINE_FIELDS
    ]
    return schema


def _project_interpretation_payload(
    payload: Any,
    *,
    cell_evidence: Sequence[PreexperimentRawResultEvidence],
) -> dict[str, Any]:
    """Derive evidence copies and scope flags from verified raw cell results."""

    if not isinstance(payload, Mapping):
        raise SystemPlanPreexperimentError("预实验解释响应必须为 JSON 对象")
    limited_supported = any(
        item.result.status == "succeeded" for item in cell_evidence
    )
    projected = dict(payload)
    projected.update(
        {
            "schema_version": "system-plan-preexperiment-interpretation-v1",
            "evidence_lines_zh": [
                item.evidence_line_zh for item in cell_evidence
            ],
            "feasibility_status": (
                "limited_scope_supported"
                if limited_supported
                else "not_supported"
            ),
            "treatment_effect_measured": False,
            "full_experiment_completed": False,
        }
    )
    return projected


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _evidence_line(result: OfficialCellResult) -> str:
    fields = (
        f"系统={result.system_name}",
        f"数据类型={result.data_type}",
        f"条件={result.condition}",
        f"随机种子={result.seed}",
        f"状态={result.status}",
        f"导数NMSE={_json_value(result.derivative_nmse)}",
        f"验证NMSE={_json_value(result.validation_nmse)}",
        f"入选项数={_json_value(result.selected_term_count)}",
        f"训练目标打乱后方程变化={_json_value(result.equation_changed_on_shuffled_training)}",
        f"运行秒数={_json_value(result.wall_time_seconds)}",
        f"失败原因={_json_value(result.failure_reason)}",
    )
    return "预实验原始结果：" + "，".join(fields) + "。"


def _guard_interpretation_numbers(*, text: str, evidence_lines: Sequence[str]) -> None:
    residual = text
    for line in evidence_lines:
        if residual.count(line) != 1:
            raise SystemPlanPreexperimentError("计划结果段必须逐字且仅一次包含每条证据行")
        residual = residual.replace(line, "", 1)
    invented = tuple(_NUMBER_PATTERN.findall(residual))
    if invented:
        raise SystemPlanPreexperimentError(
            f"预实验解释在机械证据行外新增了数字：{list(invented)}"
        )


def _select_systems(
    *, direction: ResearchDirectionCandidate, panel: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    raw_systems = panel.get("systems")
    if not isinstance(raw_systems, Sequence) or isinstance(raw_systems, str | bytes):
        raise SystemPlanPreexperimentError("公开开发面板缺少 systems")
    by_name = {
        str(item.get("system_name")): dict(item)
        for item in raw_systems
        if isinstance(item, Mapping) and item.get("system_name")
    }
    missing = [name for name in direction.target_systems if name not in by_name]
    if missing:
        raise SystemPlanPreexperimentError(
            f"入选方向引用了公开面板之外的目标系统：{missing}"
        )
    selected: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for name in direction.target_systems:
        item = by_name[name]
        data_type = str(item.get("data_type"))
        if data_type not in seen_types:
            selected.append(item)
            seen_types.add(data_type)
        if len(selected) == 2:
            break
    if not selected:
        raise SystemPlanPreexperimentError("入选方向没有可执行的公开目标系统")
    return tuple(selected)


def _verify_raw_result(
    *, output_root: Path, spec: OfficialCellSpec, result: OfficialCellResult
) -> PreexperimentRawResultEvidence:
    path = output_root / "cells" / spec.stage / spec.attempt_id / "result.json"
    if not path.is_file():
        raise SystemPlanPreexperimentError(f"预实验原始结果缺失：{path}")
    try:
        relative = path.resolve().relative_to(output_root.resolve()).as_posix()
    except ValueError as exc:
        raise SystemPlanPreexperimentError("预实验原始结果逃逸输出目录") from exc
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded_hash = payload.get("result_hash")
    expected_hash = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "result_hash"}
    )
    if recorded_hash != expected_hash or result.result_hash != recorded_hash:
        raise SystemPlanPreexperimentError("预实验 raw result_hash 不可重放")
    return PreexperimentRawResultEvidence(
        spec=spec,
        result=result,
        raw_result_relative_path=relative,
        raw_result_file_sha256=file_hash(path),
        evidence_line_zh=_evidence_line(result),
    )


def _interpretation_messages(
    *,
    lineage_id: str,
    direction: ResearchDirectionCandidate,
    cell_evidence: Sequence[PreexperimentRawResultEvidence],
    prior_findings: Sequence[str],
    previous_response: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    system = (
        "你是该科研系统的预实验结果解释主 Agent。请根据真实、网络隔离的基线可行性"
        "预实验原始结果，用简体中文撰写将进入《科学假设与研究计划》的实验结果段。"
        "这次预实验只验证公开数据、固定指标与执行链在有限目标上的可运行性，没有运行"
        "拟议干预，也没有测量新方法的处理效应。不得把基线可行性写成假设成立、创新已"
        "证实或正式实验完成。不要返回 schema_version、evidence_lines_zh、"
        "feasibility_status、treatment_effect_measured 或 full_experiment_completed；"
        "编排器会从已验证的原始单元机械投影这些字段。plan_results_zh "
        "必须逐字且仅一次包含每条证据行。所有数字只能出现在这些原始证据行中，其他"
        "中文解释不得新增数字。若没有单元 succeeded，必须在解释中明确说明可行性未建立。"
        "plan_results_zh 必须明确包含"
        "‘预实验’、‘未测量’以及‘处理效应’或‘干预效应’。先在非空 reasoning_content 中"
        "完成证据核对，再只返回满足给定 JSON Schema 的对象。"
    )
    payload: dict[str, Any] = {
        "lineage_id": lineage_id,
        "selected_direction_hash": canonical_model_hash(
            direction.model_dump(mode="json")
        ),
        "selected_direction_title": direction.title,
        "evidence_lines_zh": [item.evidence_line_zh for item in cell_evidence],
        "mechanical_limited_feasibility_supported": any(
            item.result.status == "succeeded" for item in cell_evidence
        ),
        "response_schema": _preexperiment_response_schema(),
    }
    if prior_findings:
        payload["previous_refusal_findings"] = list(prior_findings)
        payload["previous_response"] = dict(previous_response or {})
        system += " 上一响应被机械门拒绝；只修复给出的缺陷，不得改变原始证据行。"
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]


def run_system_plan_preexperiment(
    *,
    lineage_id: str,
    selected_direction: ResearchDirectionCandidate,
    component_experiment_binding: ComponentExperimentBindingV2,
    frozen_plan_path: Path | str,
    autonomous_plan_path: Path | str,
    data_root: Path | str,
    public_panel: Mapping[str, Any],
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_interpretation_attempts: int = 3,
) -> SystemPlanPreexperimentArtifact:
    """Execute the real bounded probe, then let Qwen author its Chinese result."""

    if not 1 <= max_interpretation_attempts <= 3:
        raise SystemPlanPreexperimentError("预实验结果解释最多允许三次自主修复")
    output_root = Path(output_dir).resolve()
    artifact_path = output_root / _ARTIFACT_NAME
    if artifact_path.exists():
        raise SystemPlanPreexperimentError("预实验输出必须使用全新目录，禁止覆盖或偷看续写")

    direction_hash = canonical_model_hash(selected_direction.model_dump(mode="json"))
    matching_atoms = tuple(
        atom
        for atom in component_experiment_binding.prospective_components.atoms
        if atom.atom_id == selected_direction.prospective_atom_id
    )
    if len(matching_atoms) != 1 or canonical_model_hash(matching_atoms[0]) != (
        selected_direction.prospective_intervention_hash
    ):
        raise SystemPlanPreexperimentError("预实验方向没有绑定唯一前瞻干预身份")

    selected_system_payloads = _select_systems(
        direction=selected_direction, panel=public_panel
    )
    identity, frozen_panel = freeze_official_identity(
        plan_path=frozen_plan_path,
        autonomous_plan_path=autonomous_plan_path,
        data_root=data_root,
        output_dir=output_root,
        initial_candidate_count=1,
    )
    if canonical_model_hash(dict(frozen_panel)) != identity.development_panel_hash:
        raise SystemPlanPreexperimentError("预实验冻结面板哈希不一致")
    if canonical_model_hash(dict(public_panel)) != identity.development_panel_hash:
        raise SystemPlanPreexperimentError("预实验收到的公开面板不是冻结面板")
    if not identity.seeds:
        raise SystemPlanPreexperimentError("冻结面板没有可用随机种子")
    selected_seed = int(identity.seeds[0])
    all_specs = build_official_cell_specs(
        identity=identity,
        candidates=(),
        stage="baseline",
        systems=selected_system_payloads,
        seeds=(selected_seed,),
        output_dir=output_root,
    )
    selected_specs = tuple(item for item in all_specs if item.condition == "clean")
    if len(selected_specs) != len(selected_system_payloads):
        raise SystemPlanPreexperimentError("公开面板无法形成每个目标一个 clean 预实验单元")
    write_json_model(
        output_root / _SELECTED_SPECS_NAME,
        {"specs": [item.model_dump(mode="json") for item in selected_specs]},
    )
    results = execute_official_stage(
        identity=identity,
        specs=selected_specs,
        candidates=(),
        output_dir=output_root,
        timeout_seconds=300,
        maximum_parallel_cells=min(2, len(selected_specs)),
    )
    if len(results) != len(selected_specs):
        raise SystemPlanPreexperimentError("预实验结果数量与冻结单元不一致")
    cell_evidence = tuple(
        _verify_raw_result(
            output_root=output_root,
            spec=spec,
            result=result,
        )
        for spec, result in zip(selected_specs, results, strict=True)
    )

    findings: list[str] = []
    previous_response: dict[str, Any] | None = None
    final_interpretation: PreexperimentInterpretation | None = None
    final_receipt = None
    final_model_name = ""
    final_attempt = 0
    for attempt in range(1, max_interpretation_attempts + 1):
        messages = _interpretation_messages(
            lineage_id=lineage_id,
            direction=selected_direction,
            cell_evidence=cell_evidence,
            prior_findings=findings,
            previous_response=previous_response,
        )
        try:
            result = completion(
                messages=messages,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=300,
                max_tokens=3_000,
                temperature=0.2,
                thinking_mode="enabled",
                thinking_budget=2_500,
                response_schema=None,
                response_schema_name="system_plan_preexperiment_interpretation",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            findings = [f"模型调用或 JSON 解析失败：{type(exc).__name__}: {exc}"]
            continue
        receipt = record_model_authorship_receipt(
            artifact_kind="plan_preexperiment_interpretation",
            interaction_id=f"system-plan-preexperiment-interpretation-{attempt:02d}",
            attempt=attempt,
            messages=messages,
            completion=result,
            output_dir=output_root,
        )
        previous_response = (
            dict(result.parsed_json)
            if isinstance(result.parsed_json, Mapping)
            else None
        )
        try:
            projected_interpretation = _project_interpretation_payload(
                result.parsed_json,
                cell_evidence=cell_evidence,
            )
            candidate = _PreexperimentInterpretationResponse.model_validate(
                projected_interpretation
            )
            expected_status = (
                "limited_scope_supported"
                if any(item.result.status == "succeeded" for item in cell_evidence)
                else "not_supported"
            )
            if candidate.feasibility_status != expected_status:
                raise SystemPlanPreexperimentError("可行性状态与真实单元状态冲突")
            expected_lines = tuple(item.evidence_line_zh for item in cell_evidence)
            if candidate.evidence_lines_zh != expected_lines:
                raise SystemPlanPreexperimentError("未逐字继承全部原始证据行")
            _guard_interpretation_numbers(
                text=candidate.plan_results_zh, evidence_lines=expected_lines
            )
            if "qwen" not in result.model_name.casefold():
                raise SystemPlanPreexperimentError("预实验结果解释不是配置的 Qwen 模型")
            if not str(result.reasoning_text or "").strip():
                raise SystemPlanPreexperimentError("Qwen reasoning_content 为空")
        except (ValidationError, ValueError, RuntimeError) as exc:
            findings = [str(exc)]
            continue
        final_interpretation = candidate
        final_receipt = receipt
        final_model_name = result.model_name
        final_attempt = attempt
        break

    if final_interpretation is None or final_receipt is None:
        raise SystemPlanPreexperimentError(
            "Qwen 未能在自主修复预算内生成可追溯的中文预实验结果："
            + "; ".join(findings)
        )

    selected_systems = tuple(
        PreexperimentSystemSelection.model_validate(
            {
                "system_name": str(item["system_name"]),
                "data_type": str(item["data_type"]),
                "selection_rule": "first_selected_direction_target_per_data_type",
            }
        )
        for item in selected_system_payloads
    )
    all_succeeded = all(item.result.status == "succeeded" for item in cell_evidence)
    payload: dict[str, Any] = {
        "schema_version": "system-plan-preexperiment-artifact-v1",
        "lineage_id": lineage_id,
        "selected_direction_hash": direction_hash,
        "component_experiment_binding_hash": component_experiment_binding.binding_hash,
        "identity": identity.model_dump(mode="json"),
        "selected_systems": [item.model_dump(mode="json") for item in selected_systems],
        "selected_seed": selected_seed,
        "selected_condition": "clean",
        "cell_evidence": [item.model_dump(mode="json") for item in cell_evidence],
        "interpretation": final_interpretation.model_dump(mode="json"),
        "interpretation_receipt_relative_path": Path(
            final_receipt.output_path
        ).resolve().relative_to(output_root).as_posix(),
        "interpretation_receipt_hash": final_receipt.receipt_hash,
        "model_name": final_model_name,
        "authoring_attempts": final_attempt,
        "all_cells_succeeded": all_succeeded,
        "limited_feasibility_supported": any(
            item.result.status == "succeeded" for item in cell_evidence
        ),
        "sandbox_network_disabled": True,
        "preliminary_only": True,
        "treatment_effect_measured": False,
        "full_experiment_completed": False,
        "scientific_hypothesis_validated": False,
        "publication_ready": False,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    payload["output_path"] = artifact_path.as_posix()
    artifact = SystemPlanPreexperimentArtifact.model_validate(payload)
    write_json_model(artifact_path, artifact)
    return artifact
