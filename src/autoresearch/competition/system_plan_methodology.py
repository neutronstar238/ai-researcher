"""Model-selected project skills for system-authored research planning.

The orchestrator only discovers and hashes project-local ``SKILL.md`` files.  The
configured model decides which methods apply and emits a Chinese, auditable selection
trace.  Raw provider reasoning is retained in the authorship receipt but is never
treated as scientific evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_OUTPUT_NAME = "system-plan-method-skill-selection.json"
_MIN_REASONING_CHARACTERS = 200
_MAX_SELECTION_ATTEMPTS = 2


def _skill_identifier_aliases(skill_ids: Sequence[str]) -> tuple[str, ...]:
    """Return only mechanical aliases already encoded in a skill identifier.

    Qwen often shortens ``sparse-dynamics-identification`` to
    ``sparse-dynamics`` inside otherwise Chinese prose.  Those tokens are labels,
    not English exposition.  Exempt full IDs, their hyphen prefixes, and individual
    segments while keeping arbitrary Latin prose subject to the Chinese guard.
    """

    aliases: list[str] = []
    for skill_id in skill_ids:
        parts = skill_id.split("-")
        aliases.append(skill_id)
        aliases.extend(parts)
        aliases.extend("-".join(parts[:end]) for end in range(2, len(parts)))
    return tuple(dict.fromkeys(aliases))


class SystemPlanMethodologyError(RuntimeError):
    """Raised when project skills cannot be selected with auditable provenance."""


class AvailableMethodSkill(StrictFrozenModel):
    """One immutable project-local skill offered to the configured model."""

    skill_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str = Field(min_length=20)
    source_relative_path: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str = Field(min_length=50)


class SystemPlanMethodSkillSelection(StrictFrozenModel):
    """Chinese model-authored decision over available methodology skills."""

    schema_version: Literal["system-plan-method-skill-selection-v1"] = (
        "system-plan-method-skill-selection-v1"
    )
    task_classification: str = Field(min_length=20)
    selected_skill_ids: tuple[str, ...] = Field(min_length=1)
    rejected_skill_ids: tuple[str, ...]
    selection_rationale: str = Field(min_length=30)
    planned_reasoning_stages: tuple[str, ...] = Field(min_length=6)
    auditable_reasoning_summary: tuple[str, ...] = Field(min_length=5)
    non_evidence_boundary: str = Field(min_length=30)

    @model_validator(mode="after")
    def _validate_selection(self) -> SystemPlanMethodSkillSelection:
        selected = set(self.selected_skill_ids)
        rejected = set(self.rejected_skill_ids)
        if len(selected) != len(self.selected_skill_ids):
            raise SystemPlanMethodologyError("入选技能编号不得重复")
        if len(rejected) != len(self.rejected_skill_ids):
            raise SystemPlanMethodologyError("拒绝技能编号不得重复")
        overlap = sorted(selected & rejected)
        if overlap:
            raise SystemPlanMethodologyError(
                f"技能不得同时入选和拒绝：{overlap}"
            )
        language_failures = non_chinese_prose_fields(
            {
                "task_classification": self.task_classification,
                "selection_rationale": self.selection_rationale,
                "planned_reasoning_stages": self.planned_reasoning_stages,
                "auditable_reasoning_summary": self.auditable_reasoning_summary,
                "non_evidence_boundary": self.non_evidence_boundary,
            },
            exempt_identifiers=_skill_identifier_aliases(
                (*self.selected_skill_ids, *self.rejected_skill_ids)
            ),
        )
        if language_failures:
            raise SystemPlanMethodologyError(
                f"方法技能选择不是中文：{list(language_failures)}"
            )
        return self


class SystemPlanMethodSkillSelectionBinding(StrictFrozenModel):
    """Hash-bound methodology context passed to later model interactions."""

    selection_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: SystemPlanMethodSkillSelection
    selected_skills: tuple[AvailableMethodSkill, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_binding(self) -> SystemPlanMethodSkillSelectionBinding:
        materialized_ids = tuple(item.skill_id for item in self.selected_skills)
        if materialized_ids != self.selection.selected_skill_ids:
            raise SystemPlanMethodologyError(
                "技能选择编号与物化 SKILL.md 顺序不一致"
            )
        return self


class SystemPlanMethodSkillSelectionArtifact(StrictFrozenModel):
    """Persisted skill decision, exact skill bytes, and provider receipt."""

    schema_version: Literal["system-plan-method-skill-selection-artifact-v1"] = (
        "system-plan-method-skill-selection-artifact-v1"
    )
    lineage_id: str = Field(min_length=1)
    task_signature: dict[str, Any]
    task_signature_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_skills: tuple[AvailableMethodSkill, ...] = Field(min_length=1)
    selection: SystemPlanMethodSkillSelection
    selected_skills: tuple[AvailableMethodSkill, ...] = Field(min_length=1)
    authorship_receipt_relative_path: str = Field(min_length=1)
    authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_name: str = Field(min_length=1)
    reasoning_required: Literal[True] = True
    reasoning_is_evidence: Literal[False] = False
    authored_by_model: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    created_at: datetime
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_artifact(self) -> SystemPlanMethodSkillSelectionArtifact:
        if self.task_signature_hash != canonical_model_hash(self.task_signature):
            raise SystemPlanMethodologyError("方法技能任务签名哈希不符")
        available_ids = tuple(item.skill_id for item in self.available_skills)
        accounted_ids = (
            self.selection.selected_skill_ids + self.selection.rejected_skill_ids
        )
        if len(set(accounted_ids)) != len(accounted_ids):
            raise SystemPlanMethodologyError("技能选择账本包含重复编号")
        if set(accounted_ids) != set(available_ids):
            raise SystemPlanMethodologyError("技能选择未完整覆盖可用技能")
        selected_by_id = {item.skill_id: item for item in self.available_skills}
        expected_selected = tuple(
            selected_by_id[skill_id]
            for skill_id in self.selection.selected_skill_ids
        )
        if self.selected_skills != expected_selected:
            raise SystemPlanMethodologyError("物化技能与模型入选顺序不一致")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected_hash:
            raise SystemPlanMethodologyError("方法技能选择制品哈希不符")
        return self

    def binding(self) -> SystemPlanMethodSkillSelectionBinding:
        return SystemPlanMethodSkillSelectionBinding(
            selection_artifact_hash=self.artifact_hash,
            selection=self.selection,
            selected_skills=self.selected_skills,
        )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _frontmatter(text: str, *, path: Path) -> dict[str, Any]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        raise SystemPlanMethodologyError(f"技能缺少 YAML frontmatter：{path}")
    try:
        stop = next(
            index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise SystemPlanMethodologyError(
            f"技能 YAML frontmatter 未闭合：{path}"
        ) from exc
    parsed = yaml.safe_load("\n".join(lines[1:stop]))
    if not isinstance(parsed, Mapping):
        raise SystemPlanMethodologyError(f"技能 YAML frontmatter 无效：{path}")
    return dict(parsed)


def load_project_method_skills(
    skill_root: Path | str,
) -> tuple[AvailableMethodSkill, ...]:
    """Discover immediate project-local skill directories in stable order."""

    root = Path(skill_root).resolve()
    if not root.is_dir():
        raise SystemPlanMethodologyError(f"项目方法技能目录不存在：{root}")
    skills: list[AvailableMethodSkill] = []
    for directory in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not directory.is_dir():
            continue
        skill_path = (directory / "SKILL.md").resolve()
        if not skill_path.is_file() or not skill_path.is_relative_to(root):
            continue
        text = skill_path.read_text(encoding="utf-8")
        metadata = _frontmatter(text, path=skill_path)
        skill_id = str(metadata.get("name") or "").strip()
        description = str(metadata.get("description") or "").strip()
        if skill_id != directory.name:
            raise SystemPlanMethodologyError(
                f"技能目录名与 frontmatter name 不一致：{directory.name} != {skill_id}"
            )
        skills.append(
            AvailableMethodSkill(
                skill_id=skill_id,
                description=description,
                source_relative_path=(
                    Path(root.name) / directory.name / "SKILL.md"
                ).as_posix(),
                content_sha256=_sha256_text(text),
                content=text,
            )
        )
    if not skills:
        raise SystemPlanMethodologyError(f"项目方法技能目录为空：{root}")
    return tuple(skills)


def _selection_messages(
    *,
    available_skills: Sequence[AvailableMethodSkill],
    task_signature: Mapping[str, Any],
    prior_feedback: Sequence[str],
) -> list[dict[str, str]]:
    output_example = {
        "schema_version": "system-plan-method-skill-selection-v1",
        "task_classification": "请用至少二十个中文字符完整说明任务所属的方法类别、目标与边界",
        "selected_skill_ids": ["逐字复制一个可用技能编号"],
        "rejected_skill_ids": [],
        "selection_rationale": (
            "请用至少三十个中文字符解释为何所选技能覆盖当前方法需求以及为何其余技能不适用"
        ),
        "planned_reasoning_stages": [
            "先核对冻结证据的来源、完整性和允许用途。",
            "再区分事实记录、探索关联与尚未验证的解释。",
            "随后逐项比较可用技能与当前任务边界。",
            "接着设计反事实、负对照和正交诊断步骤。",
            "然后检查分析单位、预算、失败分支与可证伪性。",
            "最后复核真实文献、新颖性边界和非证据声明。",
        ],
        "auditable_reasoning_summary": [
            "说明任务分类及其与冻结证据之间的关系。",
            "说明每个入选技能解决的独立方法问题。",
            "说明每个未入选技能不适用的具体边界。",
            "说明技能之间是否存在重复、冲突或遗漏。",
            "说明最终选择不构成科研事实或实验结论。",
        ],
        "non_evidence_boundary": (
            "请用至少三十个中文字符明确技能与模型推理只约束工作方法，不构成科学证据或实验结论"
        ),
    }
    instruction = (
        "你是自主科研系统的方法技能路由器，不得提出具体假设、算法方案、实验结果或研究计划。"
        "只根据任务签名和 SKILL.md 的 name/description 决定哪些项目技能适用于后续研究机会发现。"
        "必须在 reasoning_content 中依次完成任务分类、逐技能适用性比较、冲突检查和最终选择；"
        "程序要求 reasoning_content 非空且至少二百字符，但它只用于过程审计，绝不是科学证据。"
        "JSON 中用简体中文给出精炼、可复核的决策摘要；selected 与 rejected 必须无重复地完整"
        "覆盖全部可用技能，且至少选择一个。planned_reasoning_stages 必须给出至少六个后续阶段，"
        "明确先证据、后解释、再反事实与对照、最后资源和文献审查。技能编号是允许逐字复制的"
        "机器标识，但每条审计摘要必须以中文解释为主，不能只写技能编号加少量中文。"
        "task_classification 至少二十个字符；selection_rationale 与 non_evidence_boundary "
        "各至少三十个字符。只返回一"
        "个 JSON 值对象，严禁返回 JSON Schema、$defs、properties、字段说明或 Markdown。"
        "下面只是值骨架；不得照抄占位文本："
        + json.dumps(
            output_example,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    if prior_feedback:
        instruction += "\n\n上一轮技能选择无效，只修复精确错误：" + json.dumps(
            list(prior_feedback), ensure_ascii=False
        )
    return [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task_signature": dict(task_signature),
                    "available_method_skill_metadata": [
                        {
                            "skill_id": item.skill_id,
                            "description": item.description,
                            "source_relative_path": item.source_relative_path,
                            "content_sha256": item.content_sha256,
                        }
                        for item in available_skills
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]


def _selection_findings(
    *,
    selection: SystemPlanMethodSkillSelection,
    available_skills: Sequence[AvailableMethodSkill],
) -> tuple[str, ...]:
    available_ids = {item.skill_id for item in available_skills}
    accounted = selection.selected_skill_ids + selection.rejected_skill_ids
    findings: list[str] = []
    unknown = sorted(set(accounted) - available_ids)
    missing = sorted(available_ids - set(accounted))
    if unknown:
        findings.append(f"技能选择引用未知编号：{unknown}")
    if missing:
        findings.append(f"技能选择未处理可用编号：{missing}")
    return tuple(findings)


def _raw_selection_validation_findings(
    payload: Mapping[str, Any],
    *,
    available_skills: Sequence[AvailableMethodSkill],
) -> tuple[str, ...]:
    """Aggregate actionable shape and Chinese failures before Pydantic parsing."""

    findings: list[str] = []
    if payload.get("schema_version") != "system-plan-method-skill-selection-v1":
        findings.append("[METHOD_SCHEMA] schema_version 必须使用方法技能选择 v1")
    string_rules = (
        ("task_classification", 20, "任务分类"),
        ("selection_rationale", 30, "选择理由"),
        ("non_evidence_boundary", 30, "非证据边界"),
    )
    prose_fields: dict[str, str | Sequence[str]] = {}
    for key, minimum, label in string_rules:
        value = payload.get(key)
        if not isinstance(value, str):
            findings.append(f"[METHOD_SCHEMA] {label}必须是字符串")
        elif len(value) < minimum:
            findings.append(
                f"[METHOD_LENGTH] {label}至少需要{minimum}个字符，当前只有{len(value)}个"
            )
        else:
            prose_fields[key] = value
    sequence_rules = (
        ("selected_skill_ids", 1, "入选技能编号"),
        ("rejected_skill_ids", 0, "未入选技能编号"),
        ("planned_reasoning_stages", 6, "计划推理阶段"),
        ("auditable_reasoning_summary", 5, "可审计推理摘要"),
    )
    for key, minimum, label in sequence_rules:
        value = payload.get(key)
        if not isinstance(value, list | tuple) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            findings.append(f"[METHOD_SCHEMA] {label}必须是非空字符串数组")
            continue
        if len(value) < minimum:
            findings.append(
                f"[METHOD_LENGTH] {label}至少需要{minimum}项，当前只有{len(value)}项"
            )
        if key in {"planned_reasoning_stages", "auditable_reasoning_summary"}:
            prose_fields[key] = tuple(value)
    if prose_fields:
        failures = non_chinese_prose_fields(
            prose_fields,
            exempt_identifiers=_skill_identifier_aliases(
                tuple(item.skill_id for item in available_skills)
            ),
        )
        findings.extend(
            f"[METHOD_LANGUAGE] {field} 必须以简体中文解释为主"
            for field in failures
        )
    return tuple(findings)


def run_system_plan_method_skill_selection(
    *,
    lineage_id: str,
    task_signature: Mapping[str, Any],
    skill_root: Path | str,
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_attempts: int = _MAX_SELECTION_ATTEMPTS,
    clock: datetime | None = None,
) -> SystemPlanMethodSkillSelectionArtifact:
    """Have the configured model select project skills with mandatory reasoning."""

    if max_attempts < 1:
        raise SystemPlanMethodologyError("方法技能选择尝试次数必须为正数")
    available_skills = load_project_method_skills(skill_root)
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    feedback: tuple[str, ...] = ()
    final_receipt: ModelAuthorshipReceipt | None = None
    final_result: LLMJsonCompletionResult | None = None
    final_selection: SystemPlanMethodSkillSelection | None = None
    for attempt in range(1, max_attempts + 1):
        messages = _selection_messages(
            available_skills=available_skills,
            task_signature=task_signature,
            prior_feedback=feedback,
        )
        try:
            result = completion(
                messages=messages,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=300,
                max_tokens=8_000,
                temperature=0.2,
                thinking_mode="enabled",
                thinking_budget=5_000,
                response_schema=None,
                response_schema_name="system_plan_method_skill_selection",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            feedback = (
                "方法技能选择模型调用或 JSON 解析失败："
                f"{type(exc).__name__}: {exc}",
            )
            continue
        receipt = record_model_authorship_receipt(
            artifact_kind="plan_method_skill_selection",
            interaction_id=f"system-plan-method-skill-selection-attempt-{attempt:02d}",
            attempt=attempt,
            messages=messages,
            completion=result,
            output_dir=output_root,
            clock=clock,
        )
        reasoning = str(result.reasoning_text or "").strip()
        if len(reasoning) < _MIN_REASONING_CHARACTERS:
            feedback = (
                "Qwen 未返回至少二百字符的 reasoning_content，方法选择不可审计",
            )
            continue
        raw_findings = _raw_selection_validation_findings(
            result.parsed_json,
            available_skills=available_skills,
        )
        if raw_findings:
            feedback = raw_findings
            continue
        try:
            selection = SystemPlanMethodSkillSelection.model_validate(
                result.parsed_json
            )
        except (
            ValidationError,
            SystemPlanMethodologyError,
            ValueError,
        ) as exc:
            feedback = (f"方法技能选择结构或中文校验失败：{exc}",)
            continue
        findings = _selection_findings(
            selection=selection,
            available_skills=available_skills,
        )
        if findings:
            feedback = findings
            continue
        final_receipt = receipt
        final_result = result
        final_selection = selection
        break
    if final_receipt is None or final_result is None or final_selection is None:
        raise SystemPlanMethodologyError(
            "系统未能产生可审计的方法技能选择；最终反馈："
            f"{list(feedback)}"
        )
    by_id = {item.skill_id: item for item in available_skills}
    selected_skills = tuple(
        by_id[skill_id] for skill_id in final_selection.selected_skill_ids
    )
    receipt_path = Path(final_receipt.output_path).resolve()
    payload: dict[str, Any] = {
        "schema_version": "system-plan-method-skill-selection-artifact-v1",
        "lineage_id": lineage_id,
        "task_signature": dict(task_signature),
        "task_signature_hash": canonical_model_hash(dict(task_signature)),
        "available_skills": [
            item.model_dump(mode="json") for item in available_skills
        ],
        "selection": final_selection.model_dump(mode="json"),
        "selected_skills": [
            item.model_dump(mode="json") for item in selected_skills
        ],
        "authorship_receipt_relative_path": receipt_path.relative_to(
            output_root
        ).as_posix(),
        "authorship_receipt_hash": final_receipt.receipt_hash,
        "model_name": final_result.model_name,
        "reasoning_required": True,
        "reasoning_is_evidence": False,
        "authored_by_model": True,
        "hand_written_scientific_prose_count": 0,
        "created_at": (clock or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    output_path = output_root / _OUTPUT_NAME
    payload["output_path"] = output_path.as_posix()
    artifact = SystemPlanMethodSkillSelectionArtifact.model_validate(payload)
    write_json_model(output_path, artifact)
    return artifact
