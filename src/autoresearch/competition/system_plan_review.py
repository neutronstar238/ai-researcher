"""Adversarial, model-authored review before a research plan can reach a human.

The deterministic plan grader catches shape, provenance, language, and executable
contract defects.  It cannot decide whether a mechanism reverses a known numerical
effect, merely repackages prior work, confounds method and implementation, or uses an
outcome that cannot answer the stated question.  This module gives a separate model
interaction the complete plan, retrieved literature catalog, and retained evidence,
then preserves its exact response.  The reviewer may reject and teach the author; it
never writes replacement scientific prose into the plan.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import record_model_authorship_receipt
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.schemas import ResearchPlan

_ACCEPTED_REVIEW_NAME = "system-plan-critical-review.json"


class SystemPlanReviewError(RuntimeError):
    """Raised when a critical plan review is absent, malformed, or contradictory."""


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


def _missing_required_chinese_prose(
    fields: Mapping[str, str | Sequence[str]],
) -> tuple[str, ...]:
    """Reject blank or non-Chinese prose without imposing stylistic length quotas."""

    failed: list[str] = []
    for name, value in fields.items():
        items = (value,) if isinstance(value, str) else tuple(value)
        for index, item in enumerate(items):
            text = str(item).strip()
            if not text or not any(_is_cjk_ideograph(char) for char in text):
                failed.append(name if isinstance(value, str) else f"{name}[{index}]")
    return tuple(failed)


class PriorWorkComparison(StrictFrozenModel):
    """One model-authored comparison against a real retrieved catalog entry."""

    reference_index: int = Field(ge=1)
    overlap: str = Field(min_length=1)
    claimed_difference: str = Field(min_length=1)
    remaining_novelty_risk: str = Field(min_length=1)


class CriticalPlanAssessment(StrictFrozenModel):
    """Structured critical-thinking verdict; every scientific sentence is Chinese."""

    schema_version: Literal["critical-plan-assessment-v1"] = (
        "critical-plan-assessment-v1"
    )
    overall_assessment: str = Field(min_length=1)
    closest_prior_work: tuple[PriorWorkComparison, ...] = Field(min_length=3)
    mechanism_critical_findings: tuple[str, ...]
    design_critical_findings: tuple[str, ...]
    evidence_semantics_critical_findings: tuple[str, ...]
    execution_critical_findings: tuple[str, ...]
    novelty_critical_findings: tuple[str, ...]
    scientific_lineage_critical_findings: tuple[str, ...]
    required_revisions: tuple[str, ...]
    mechanism_scientifically_plausible: bool
    design_can_test_the_hypothesis: bool
    evidence_semantics_valid: bool
    execution_contract_feasible: bool
    novelty_plausible_against_retrieved_work: bool
    scientific_lineage_preserved: bool
    ready_for_human_scope_review: bool

    @model_validator(mode="after")
    def _validate(self) -> CriticalPlanAssessment:
        reference_indices = tuple(
            comparison.reference_index for comparison in self.closest_prior_work
        )
        if len(set(reference_indices)) != len(reference_indices):
            raise SystemPlanReviewError(
                "closest_prior_work 必须比较至少三篇 reference_index 互不相同的文献"
            )

        gate_findings = (
            (
                "mechanism_scientifically_plausible",
                self.mechanism_scientifically_plausible,
                self.mechanism_critical_findings,
            ),
            (
                "design_can_test_the_hypothesis",
                self.design_can_test_the_hypothesis,
                self.design_critical_findings,
            ),
            (
                "evidence_semantics_valid",
                self.evidence_semantics_valid,
                self.evidence_semantics_critical_findings,
            ),
            (
                "execution_contract_feasible",
                self.execution_contract_feasible,
                self.execution_critical_findings,
            ),
            (
                "novelty_plausible_against_retrieved_work",
                self.novelty_plausible_against_retrieved_work,
                self.novelty_critical_findings,
            ),
            (
                "scientific_lineage_preserved",
                self.scientific_lineage_preserved,
                self.scientific_lineage_critical_findings,
            ),
        )
        actionable_items = (
            *(finding for _, _, findings in gate_findings for finding in findings),
            *self.required_revisions,
        )
        if any(not item.strip() for item in actionable_items):
            raise SystemPlanReviewError(
                "critical findings 与 required revisions 不得包含空白占位项"
            )
        false_gates_without_specific_findings = tuple(
            label
            for label, passed, findings in gate_findings
            if not passed and not findings
        )
        distinct_required_revisions = {
            revision.strip() for revision in self.required_revisions if revision.strip()
        }
        if len(distinct_required_revisions) < len(
            false_gates_without_specific_findings
        ):
            raise SystemPlanReviewError(
                "每个 false 科学门禁都必须有对应的 critical finding 或独立的 "
                "required revision："
                f"{list(false_gates_without_specific_findings)}"
            )

        critical = (
            *self.mechanism_critical_findings,
            *self.design_critical_findings,
            *self.evidence_semantics_critical_findings,
            *self.execution_critical_findings,
            *self.novelty_critical_findings,
            *self.scientific_lineage_critical_findings,
        )
        expected_ready = (
            self.mechanism_scientifically_plausible
            and self.design_can_test_the_hypothesis
            and self.evidence_semantics_valid
            and self.execution_contract_feasible
            and self.novelty_plausible_against_retrieved_work
            and self.scientific_lineage_preserved
            and not critical
            and not self.required_revisions
        )
        if self.ready_for_human_scope_review != expected_ready:
            raise SystemPlanReviewError(
                "critical-review readiness contradicts its findings or booleans"
            )
        prose: dict[str, str | tuple[str, ...]] = {
            "overall_assessment": self.overall_assessment,
            "mechanism_critical_findings": self.mechanism_critical_findings,
            "design_critical_findings": self.design_critical_findings,
            "evidence_semantics_critical_findings": (
                self.evidence_semantics_critical_findings
            ),
            "execution_critical_findings": self.execution_critical_findings,
            "novelty_critical_findings": self.novelty_critical_findings,
            "scientific_lineage_critical_findings": (
                self.scientific_lineage_critical_findings
            ),
            "required_revisions": self.required_revisions,
            "closest_prior_work.overlap": tuple(
                item.overlap for item in self.closest_prior_work
            ),
            "closest_prior_work.claimed_difference": tuple(
                item.claimed_difference for item in self.closest_prior_work
            ),
            "closest_prior_work.remaining_novelty_risk": tuple(
                item.remaining_novelty_risk for item in self.closest_prior_work
            ),
        }
        non_chinese = _missing_required_chinese_prose(prose)
        non_chinese += non_chinese_prose_fields(prose)
        if non_chinese:
            raise SystemPlanReviewError(
                f"critical review is not Chinese: {list(non_chinese)}"
            )
        return self

    def repair_findings(self) -> tuple[str, ...]:
        """Return exact system-authored findings for the next authoring attempt."""

        return tuple(
            dict.fromkeys(
                (
                    *self.mechanism_critical_findings,
                    *self.design_critical_findings,
                    *self.evidence_semantics_critical_findings,
                    *self.execution_critical_findings,
                    *self.novelty_critical_findings,
                    *self.scientific_lineage_critical_findings,
                    *self.required_revisions,
                )
            )
        )


class SystemPlanCriticalReview(StrictFrozenModel):
    """Hash-bound review plus the exact provider call that authored it."""

    schema_version: Literal["system-plan-critical-review-v1"] = (
        "system-plan-critical-review-v1"
    )
    lineage_id: str = Field(min_length=1)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    literature_survey_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authoring_attempt: int = Field(ge=1)
    assessment: CriticalPlanAssessment
    authorship_receipt_relative_path: str
    authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_name: str = Field(min_length=1)
    authored_by_model: Literal[True] = True
    hand_written_scientific_prose_count: Literal[0] = 0
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    created_at: datetime
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> SystemPlanCriticalReview:
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"review_hash", "output_path"})
        )
        if self.review_hash != expected:
            raise SystemPlanReviewError("system plan critical-review hash mismatch")
        return self


def _critical_review_response_schema() -> dict[str, Any]:
    """Expose only scientific review judgments and prose to Qwen."""

    schema: dict[str, Any] = json.loads(
        json.dumps(CriticalPlanAssessment.model_json_schema())
    )
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise SystemPlanReviewError("critical review schema is not projectable")
    for field_name in ("schema_version", "ready_for_human_scope_review"):
        properties.pop(field_name, None)
    schema["required"] = [
        field_name
        for field_name in required
        if field_name not in {"schema_version", "ready_for_human_scope_review"}
    ]
    return schema


def _project_critical_review_payload(payload: Any) -> dict[str, Any]:
    """Derive the formal version and readiness conjunction without changing science."""

    if not isinstance(payload, Mapping):
        raise SystemPlanReviewError("critical review response must be a JSON object")
    projected = dict(payload)
    critical_fields = (
        "mechanism_critical_findings",
        "design_critical_findings",
        "evidence_semantics_critical_findings",
        "execution_critical_findings",
        "novelty_critical_findings",
        "scientific_lineage_critical_findings",
    )
    gate_fields = (
        "mechanism_scientifically_plausible",
        "design_can_test_the_hypothesis",
        "evidence_semantics_valid",
        "execution_contract_feasible",
        "novelty_plausible_against_retrieved_work",
        "scientific_lineage_preserved",
    )
    projected["schema_version"] = "critical-plan-assessment-v1"
    projected["ready_for_human_scope_review"] = (
        all(projected.get(field_name) is True for field_name in gate_fields)
        and all(projected.get(field_name) in ([], ()) for field_name in critical_fields)
        and projected.get("required_revisions") in ([], ())
    )
    return projected


def _critical_review_messages(
    *,
    plan: ResearchPlan,
    literature_survey: Mapping[str, Any],
    frozen_evidence_context: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Build the one canonical prompt accepted as a critical plan review."""

    raw_catalog = list(literature_survey.get("retrieved_catalog") or [])
    if len(raw_catalog) < 3:
        raise SystemPlanReviewError(
            "critical review requires at least three real retrieved papers"
        )
    catalog = [
        {
            **{
                key: value
                for key, value in item.items()
                if key != "retrieval_index"
            },
            "reference_index": position,
        }
        for position, item in enumerate(raw_catalog, 1)
    ]
    selected_method_skills = frozen_evidence_context.get(
        "system_selected_method_skills"
    )
    instruction = (
        "你是独立于计划作者调用的严格科研评审器。只审查，不替作者重写计划。"
        "请用最严厉但可操作的标准，核对以下方面：研究问题是否确实填补真实文献缺口；"
        "机制陈述是否符合数值分析与已知科学原理；实验是否能区分机制与实现质量；"
        "主要结局、独立分析单位、基线、分层、选择过程与停止规则是否预先固定；"
        "是否存在 HARKing、选择偏差、多重比较、样本量/功效、构念效度或外推问题；"
        "每个既有数字是否被用于原来的语义，而非只因数值恰好出现过就挪作新阈值；"
        "代码合同能否真正实现并检验计划；所谓创新是否只是给既有方法换名或拼接。"
        "还必须把计划逐项反查到上下文中的 system_audited_research_opportunity_map 与 "
        "system_selected_research_direction：计划不得更换机会格的可操作构念、目标系统、"
        "替代解释和可判别观测，也不得只保留方法 token 却偷换科学问题。任何脱钩都属于"
        "scientific_lineage_critical_findings，并必须将 scientific_lineage_preserved "
        "设为 false；不得用其他门禁的 true 掩盖谱系脱钩。"
        "必须逐项比较至少三篇 reference_index 互不相同的真实检索文献。若摘要不足以"
        "支持肯定判断，应记录不确定性并要求补证，不能猜测。只有所有 critical finding "
        "和 required revision 都为空，六个布尔门都为 true 时，计划才可进入人工范围复核。"
        "不要返回 schema_version 或 ready_for_human_scope_review；编排器会从六个科学门"
        "与全部 findings/revisions 的严格合取中推导。所有评审散文必须为简体中文，"
        "论文原题、方法名、指标名和代码标识符保留原文。"
        + (
            "必须在 reasoning_content 中逐项应用独立消息内系统自主选择的 SKILL.md；"
            "程序会拒绝空的 reasoning_content，且该过程记录不是科学证据。"
            if isinstance(selected_method_skills, Mapping)
            else ""
        )
        + "返回且只返回满足下列 JSON schema 的对象："
        + json.dumps(
            _critical_review_response_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    evidence_context = dict(frozen_evidence_context)
    evidence_context.pop("system_selected_method_skills", None)
    user_payload = {
        "candidate_plan": plan.model_dump(mode="json"),
        "retrieved_literature_catalog": catalog,
        "immutable_protocol_and_retained_evidence": evidence_context,
    }
    messages = [{"role": "system", "content": instruction}]
    if isinstance(selected_method_skills, Mapping):
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "system_selected_project_method_skills",
                        **dict(selected_method_skills),
                        "use_boundary": (
                            "技能只约束推理方法，不是事实、文献、假设、计划或实验结果。"
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
        }
    )
    return messages


def review_system_authored_plan(
    *,
    lineage_id: str,
    plan: ResearchPlan,
    plan_hash: str,
    literature_survey: Mapping[str, Any],
    frozen_evidence_context: Mapping[str, Any],
    authoring_attempt: int,
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    clock: datetime | None = None,
) -> SystemPlanCriticalReview:
    """Have a separate adversarial interaction review one exact candidate plan."""

    output_root = Path(output_dir).resolve()
    raw_catalog = list(literature_survey.get("retrieved_catalog") or [])
    selected_method_skills = frozen_evidence_context.get(
        "system_selected_method_skills"
    )
    messages = _critical_review_messages(
        plan=plan,
        literature_survey=literature_survey,
        frozen_evidence_context=frozen_evidence_context,
    )
    result = completion(
        messages=messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=300,
        max_tokens=6_000,
        temperature=0.1,
        thinking_mode="enabled",
        thinking_budget=4_000,
        response_schema=None,
        response_schema_name="critical_plan_assessment",
    )
    receipt = record_model_authorship_receipt(
        artifact_kind="plan_critical_review",
        interaction_id=f"system-plan-critical-review-attempt-{authoring_attempt:02d}",
        attempt=authoring_attempt,
        messages=messages,
        completion=result,
        output_dir=output_root,
        clock=clock,
    )
    if (
        isinstance(selected_method_skills, Mapping)
        and not str(result.reasoning_text or "").strip()
    ):
        raise SystemPlanReviewError(
            "Qwen 未返回非空 reasoning_content，计划审查方法链不可审计"
        )
    assessment = CriticalPlanAssessment.model_validate(
        _project_critical_review_payload(result.parsed_json)
    )
    invalid_indices = sorted(
        {
            item.reference_index
            for item in assessment.closest_prior_work
            if item.reference_index > len(raw_catalog)
        }
    )
    if invalid_indices:
        raise SystemPlanReviewError(
            f"critical review cited absent literature indices: {invalid_indices}"
        )
    now = clock or datetime.now(timezone.utc)
    path = (
        output_root / _ACCEPTED_REVIEW_NAME
        if assessment.ready_for_human_scope_review
        else output_root
        / "reviews"
        / f"system-plan-critical-review-attempt-{authoring_attempt:02d}.json"
    )
    receipt_path = Path(receipt.output_path).resolve()
    try:
        receipt_relative = receipt_path.relative_to(output_root).as_posix()
    except ValueError as exc:
        raise SystemPlanReviewError("critical-review receipt escapes lineage") from exc
    payload: dict[str, Any] = {
        "schema_version": "system-plan-critical-review-v1",
        "lineage_id": lineage_id,
        "plan_hash": plan_hash,
        "literature_survey_hash": str(literature_survey["survey_hash"]),
        "authoring_attempt": authoring_attempt,
        "assessment": assessment.model_dump(mode="json"),
        "authorship_receipt_relative_path": receipt_relative,
        "authorship_receipt_hash": receipt.receipt_hash,
        "model_name": result.model_name,
        "authored_by_model": True,
        "hand_written_scientific_prose_count": 0,
        "is_scientific_evidence": False,
        "execution_authorized": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["review_hash"] = canonical_model_hash(payload)
    payload["output_path"] = path.as_posix()
    review = SystemPlanCriticalReview.model_validate(payload)
    write_json_model(path, review)
    return review
