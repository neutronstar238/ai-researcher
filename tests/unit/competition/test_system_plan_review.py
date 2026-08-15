"""A formally valid plan still needs adversarial scientific and novelty review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.system_plan_review import (
    CriticalPlanAssessment,
    SystemPlanReviewError,
    review_system_authored_plan,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.schemas import ResearchPlan, ResearchPlanStatus


def _plan() -> ResearchPlan:
    return ResearchPlan.model_validate(
        {
            "project_id": "review-plan",
            "candidate_id": "candidate-review",
            "title": "用于评审的中文机制计划",
            "abstract": "本计划说明问题、待检验机制与可能被反驳的预期。",
            "problem_statement": "既有签名结果留下了未解释的跨系统差异[1]。",
            "rationale": "候选机制必须与最近方法逐项比较，不能只更换名称[2]。",
            "technical_details": "训练、冻结与预测阶段保持隔离，并记录全部失败。",
            "datasets": {
                "source": "冻结数据根目录提供训练与验证输入。",
                "target": "时间上隔离的测试切片只用于最终评估。",
            },
            "methods": "采用可审计候选并与冻结基线作配对比较[3]。",
            "experiments": [
                "先运行不接触测试结果的试运行。",
                "再运行完整候选与基线矩阵。",
                "最后按冻结规则汇总独立系统。",
            ],
            "baselines": ["冻结基线用于同单元配对比较。"],
            "metrics": ["NMSE 用于衡量导数预测误差。"],
            "expected_results": "若效果未超过冻结阈值则假设被反驳，零结果同样有效。",
            "code_agent_brief": (
                "运行 python /harness/runner.py，并实现可达调用。"
                "required_method_tokens=[spectral, stlsq]"
            ),
            "risks_and_alternatives": [
                "若机制与既有方法重合，则停止执行并重新规划。",
                "若测量无法区分机制，则把结论限制为描述性结果。",
            ],
            "references": ["真实检索文献目录"],
            "evidence_refs": ["signed-package.json"],
            "status": ResearchPlanStatus.READY_FOR_APPROVAL,
        }
    )


def _assessment(*, ready: bool = True, index: int = 1) -> dict[str, Any]:
    findings = [] if ready else ["机制陈述与给出的数值分析原理相冲突。"]
    return {
        "schema_version": "critical-plan-assessment-v1",
        "overall_assessment": "该计划已逐项核对机制、设计、证据语义、执行合同与真实文献中的创新重合风险。",
        "closest_prior_work": [
            {
                "reference_index": index,
                "overlap": "该文献与计划都使用相同的候选方程识别框架。",
                "claimed_difference": "计划声称在冻结执行边界内增加可检验机制。",
                "remaining_novelty_risk": "仍需用消融证明差异不是已有组件的直接拼接。",
            },
            {
                "reference_index": 2,
                "overlap": "该文献与计划都处理含噪观测下的结构发现。",
                "claimed_difference": "计划使用不同的冻结选择规则与配对结果。",
                "remaining_novelty_risk": "文献摘要不足以排除实现细节已经公开。",
            },
            {
                "reference_index": 3,
                "overlap": "该文献与计划都强调跨系统的稳健性评估。",
                "claimed_difference": "计划预注册了失败保留与分层门禁。",
                "remaining_novelty_risk": "协议创新不能替代方法本身的创新。",
            },
        ],
        "mechanism_critical_findings": findings,
        "design_critical_findings": [],
        "evidence_semantics_critical_findings": [],
        "execution_critical_findings": [],
        "novelty_critical_findings": [],
        "scientific_lineage_critical_findings": [],
        "required_revisions": findings,
        "mechanism_scientifically_plausible": ready,
        "design_can_test_the_hypothesis": True,
        "evidence_semantics_valid": True,
        "execution_contract_feasible": True,
        "novelty_plausible_against_retrieved_work": True,
        "scientific_lineage_preserved": True,
        "ready_for_human_scope_review": ready,
    }


def _result(
    payload: dict[str, Any],
    *,
    reasoning_text: str | None = None,
) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.example/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.example/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        usage={"prompt_tokens": 100, "completion_tokens": 200},
        temperature=0.1,
        reasoning_text=reasoning_text,
        reasoning_transport=(
            "dashscope_enable_thinking" if reasoning_text is not None else "absent"
        ),
    )


def _survey() -> dict[str, Any]:
    return {
        "survey_hash": "a" * 64,
        "retrieved_catalog": [
            {"retrieval_index": index, "title": f"paper {index}", "abstract": "x"}
            for index in range(3)
        ],
    }


def test_accepted_review_binds_plan_and_exact_model_receipt(tmp_path: Path) -> None:
    plan = _plan()
    qwen_payload = _assessment()
    qwen_payload.pop("schema_version")
    qwen_payload.pop("ready_for_human_scope_review")
    review = review_system_authored_plan(
        lineage_id="review-lineage",
        plan=plan,
        plan_hash=canonical_model_hash(plan.model_dump(mode="json")),
        literature_survey=_survey(),
        frozen_evidence_context={"signed_prior": {"effect": -1.0}},
        authoring_attempt=2,
        output_dir=tmp_path,
        completion=lambda **_: _result(qwen_payload),
    )

    assert review.assessment.ready_for_human_scope_review is True
    assert (tmp_path / "system-plan-critical-review.json").is_file()
    assert (tmp_path / review.authorship_receipt_relative_path).is_file()
    assert review.authored_by_model is True
    assert review.hand_written_scientific_prose_count == 0
    assert review.execution_authorized is False
    receipt = json.loads(
        (tmp_path / review.authorship_receipt_relative_path).read_text(
            encoding="utf-8"
        )
    )
    assert "ready_for_human_scope_review" not in receipt["parsed_payload"]
    assert '"ready_for_human_scope_review"' not in receipt["messages"][0]["content"]


def test_review_schema_forbids_ready_with_a_critical_finding() -> None:
    payload = _assessment(ready=False)
    payload["ready_for_human_scope_review"] = True
    with pytest.raises(SystemPlanReviewError, match="contradicts"):
        CriticalPlanAssessment.model_validate(payload)


def test_concise_chinese_review_prose_is_accepted_without_length_quota() -> None:
    payload = _assessment()
    payload["overall_assessment"] = "可审查。"
    for comparison in payload["closest_prior_work"]:
        comparison["overlap"] = "有重叠。"
        comparison["claimed_difference"] = "有差异。"
        comparison["remaining_novelty_risk"] = "有风险。"

    assessment = CriticalPlanAssessment.model_validate(payload)

    assert assessment.overall_assessment == "可审查。"


def test_blank_review_prose_is_rejected_without_length_quota() -> None:
    payload = _assessment()
    payload["overall_assessment"] = "   "

    with pytest.raises(SystemPlanReviewError, match="not Chinese"):
        CriticalPlanAssessment.model_validate(payload)


def test_false_gate_without_finding_or_revision_is_rejected() -> None:
    payload = _assessment(ready=False)
    payload["mechanism_critical_findings"] = []
    payload["required_revisions"] = []

    with pytest.raises(SystemPlanReviewError, match="每个 false 科学门禁"):
        CriticalPlanAssessment.model_validate(payload)


def test_whitespace_finding_cannot_fake_an_actionable_false_gate() -> None:
    payload = _assessment(ready=False)
    payload["mechanism_critical_findings"] = ["   "]
    payload["required_revisions"] = []

    with pytest.raises(SystemPlanReviewError, match="空白占位项"):
        CriticalPlanAssessment.model_validate(payload)


def test_each_unexplained_false_gate_needs_a_distinct_required_revision() -> None:
    payload = _assessment(ready=False)
    payload["mechanism_critical_findings"] = []
    payload["design_can_test_the_hypothesis"] = False
    payload["required_revisions"] = ["必须分别修正机制定义与决定性实验后重新接受审查。"]

    with pytest.raises(SystemPlanReviewError, match="每个 false 科学门禁"):
        CriticalPlanAssessment.model_validate(payload)


def test_one_false_gate_may_be_explained_by_one_required_revision() -> None:
    payload = _assessment(ready=False)
    payload["mechanism_critical_findings"] = []

    assessment = CriticalPlanAssessment.model_validate(payload)

    assert assessment.repair_findings() == tuple(payload["required_revisions"])


def test_review_rejects_three_copies_of_the_same_prior_work() -> None:
    payload = _assessment()
    payload["closest_prior_work"] = [
        dict(payload["closest_prior_work"][0]) for _ in range(3)
    ]

    with pytest.raises(SystemPlanReviewError, match="reference_index 互不相同"):
        CriticalPlanAssessment.model_validate(payload)


def test_review_cannot_cite_a_paper_outside_retrieved_catalog(
    tmp_path: Path,
) -> None:
    plan = _plan()
    with pytest.raises(SystemPlanReviewError, match="absent literature indices"):
        review_system_authored_plan(
            lineage_id="review-lineage",
            plan=plan,
            plan_hash=canonical_model_hash(plan.model_dump(mode="json")),
            literature_survey=_survey(),
            frozen_evidence_context={},
            authoring_attempt=1,
            output_dir=tmp_path,
            completion=lambda **_: _result(_assessment(index=99)),
        )


def test_concise_nonempty_review_reasoning_is_accepted(tmp_path: Path) -> None:
    plan = _plan()
    review = review_system_authored_plan(
        lineage_id="review-concise-reasoning",
        plan=plan,
        plan_hash=canonical_model_hash(plan.model_dump(mode="json")),
        literature_survey=_survey(),
        frozen_evidence_context={"system_selected_method_skills": {}},
        authoring_attempt=1,
        output_dir=tmp_path,
        completion=lambda **_: _result(_assessment(), reasoning_text="已核对。"),
    )

    assert review.assessment.ready_for_human_scope_review is True


def test_empty_review_reasoning_is_rejected(tmp_path: Path) -> None:
    plan = _plan()
    with pytest.raises(SystemPlanReviewError, match="非空 reasoning_content"):
        review_system_authored_plan(
            lineage_id="review-empty-reasoning",
            plan=plan,
            plan_hash=canonical_model_hash(plan.model_dump(mode="json")),
            literature_survey=_survey(),
            frozen_evidence_context={"system_selected_method_skills": {}},
            authoring_attempt=1,
            output_dir=tmp_path,
            completion=lambda **_: _result(_assessment(), reasoning_text=""),
        )
