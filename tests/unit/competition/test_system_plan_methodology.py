from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.system_plan_methodology import (
    SystemPlanMethodologyError,
    load_project_method_skills,
    run_system_plan_method_skill_selection,
)
from autoresearch.llm.client import LLMJsonCompletionResult

ROOT = Path(__file__).resolve().parents[3]


def _skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    skill_dir = root / "sparse-dynamics-identification"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: sparse-dynamics-identification
description: 面向稀疏动力学发现的证据审计、单组件反事实与可证伪性检查方法。
---

# 稀疏动力学辨识

先核对证据范围，再设计单组件反事实、负对照、正交诊断与结果盲判据。
""",
        encoding="utf-8",
    )
    return root


def _selection(*, selected: str = "sparse-dynamics-identification") -> dict[str, Any]:
    return {
        "schema_version": "system-plan-method-skill-selection-v1",
        "task_classification": (
            "当前任务属于稀疏动力学方程发现中的证据归因与机制识别，而不是普通文本生成。"
        ),
        "selected_skill_ids": [selected],
        "rejected_skill_ids": [],
        "selection_rationale": (
            "该技能直接覆盖逐系统效果、联合混杂、单组件反事实和可证伪判断，适用于当前机会发现阶段。"
        ),
        "planned_reasoning_stages": [
            "先核对冻结身份和证据事实的作用范围。",
            "再区分完整效果、探索关联与跨谱系矩阵。",
            "随后列出尚未解决的证据矛盾与替代解释。",
            "只选择一个可独立操纵的流水线组件。",
            "设计负对照、敏感性对照和正交诊断。",
            "最后检查分析单位、资源上界和文献新颖性。",
        ],
        "auditable_reasoning_summary": [
            "任务包含常微分或偏微分方程发现及稀疏回归组件。",
            "冻结事实中存在不能直接进行组件归因的联合混杂。",
            "需要用单组件反事实而不是跨候选总分完成识别。",
            "需要把系统作为独立单位并保留无法判定分支。",
            "因此入选稀疏动力学辨识技能作为方法约束。",
        ],
        "non_evidence_boundary": (
            "技能内容和模型 reasoning 只约束工作方法，不构成科学证据、实验结果或已成立的机制结论。"
        ),
    }


class _Stub:
    def __init__(
        self,
        *payloads: dict[str, Any],
        reasoning_text: str | None = None,
    ) -> None:
        self.payloads = list(payloads)
        self.reasoning_text = reasoning_text
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        payload = self.payloads[len(self.calls) - 1]
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={"reasoning_tokens": 5000},
            temperature=float(kwargs["temperature"]),
            reasoning_text=self.reasoning_text,
            reasoning_transport="dashscope_enable_thinking",
        )


def test_load_project_method_skills_hashes_exact_skill_bytes(tmp_path: Path) -> None:
    skills = load_project_method_skills(_skill_root(tmp_path))

    assert [item.skill_id for item in skills] == [
        "sparse-dynamics-identification"
    ]
    assert skills[0].source_relative_path == (
        "skills/sparse-dynamics-identification/SKILL.md"
    )
    assert len(skills[0].content_sha256) == 64
    assert "单组件反事实" in skills[0].content


def test_production_catalog_offers_multiple_independently_routable_skills() -> None:
    skills = load_project_method_skills(ROOT / "skills")
    skill_ids = {item.skill_id for item in skills}

    assert skill_ids == {
        "agent-memory-evaluation",
        "causal-mechanism-identifiability",
        "numerical-scientific-computing",
        "research-novelty-triangulation",
        "sparse-dynamics-identification",
    }
    assert len({item.content_sha256 for item in skills}) == len(skills)


def test_qwen_selects_skill_with_required_reasoning_and_receipt(
    tmp_path: Path,
) -> None:
    stub = _Stub(_selection(), reasoning_text="先分类任务并逐项比较技能。" * 20)

    artifact = run_system_plan_method_skill_selection(
        lineage_id="lineage-methodology",
        task_signature={
            "stage": "research_opportunity_mapping",
            "data_types": ["ode", "pde"],
            "literature_titles": ["Sparse identification of nonlinear dynamics"],
        },
        skill_root=_skill_root(tmp_path),
        output_dir=tmp_path / "run",
        completion=stub,
    )

    assert artifact.selection.selected_skill_ids == (
        "sparse-dynamics-identification",
    )
    assert artifact.reasoning_required is True
    assert artifact.reasoning_is_evidence is False
    assert artifact.binding().selected_skills[0].content_sha256 == (
        artifact.selected_skills[0].content_sha256
    )
    assert (tmp_path / "run" / "system-plan-method-skill-selection.json").is_file()
    assert (
        tmp_path / "run" / artifact.authorship_receipt_relative_path
    ).is_file()
    assert stub.calls[0]["thinking_mode"] == "enabled"
    assert stub.calls[0]["thinking_budget"] == 5_000
    assert "reasoning_content" in stub.calls[0]["messages"][0]["content"]
    assert '"$defs"' not in stub.calls[0]["messages"][0]["content"]
    assert '"properties"' not in stub.calls[0]["messages"][0]["content"]


def test_skill_identifier_is_exempt_but_auditable_summary_stays_chinese(
    tmp_path: Path,
) -> None:
    payload = _selection()
    payload["auditable_reasoning_summary"][1] = (
        "sparse-dynamics-identification 适用于稀疏动力学证据审计与单组件反事实检查。"
    )
    stub = _Stub(payload, reasoning_text="先分类任务并逐项比较技能。" * 20)

    artifact = run_system_plan_method_skill_selection(
        lineage_id="lineage-methodology-identifier",
        task_signature={"stage": "research_opportunity_mapping"},
        skill_root=_skill_root(tmp_path),
        output_dir=tmp_path / "run",
        completion=stub,
        max_attempts=1,
    )

    assert artifact.selection.auditable_reasoning_summary[1].startswith(
        "sparse-dynamics-identification "
    )


def test_skill_identifier_aliases_are_exempt_inside_chinese_reasoning(
    tmp_path: Path,
) -> None:
    payload = _selection()
    payload["auditable_reasoning_summary"][1] = (
        "技能互补关系为：sparse-dynamics 负责领域审计，numerical 负责数值可靠性，"
        "causal 负责识别设计，novelty 负责逐篇查重，正文仍以中文解释为主。"
    )
    stub = _Stub(payload, reasoning_text="先分类任务并逐项比较技能。" * 20)

    artifact = run_system_plan_method_skill_selection(
        lineage_id="lineage-methodology-aliases",
        task_signature={"stage": "research_opportunity_mapping"},
        skill_root=_skill_root(tmp_path),
        output_dir=tmp_path / "run",
        completion=stub,
        max_attempts=1,
    )

    assert "sparse-dynamics" in artifact.selection.auditable_reasoning_summary[1]


def test_missing_qwen_reasoning_fails_closed_after_preserving_receipt(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "run"
    stub = _Stub(_selection(), reasoning_text=None)

    with pytest.raises(SystemPlanMethodologyError, match="reasoning_content"):
        run_system_plan_method_skill_selection(
            lineage_id="lineage-no-reasoning",
            task_signature={"stage": "research_opportunity_mapping"},
            skill_root=_skill_root(tmp_path),
            output_dir=output_dir,
            completion=stub,
            max_attempts=1,
        )

    assert (
        output_dir
        / "interactions"
        / "system-plan-method-skill-selection-attempt-01.json"
    ).is_file()
    assert not (output_dir / "system-plan-method-skill-selection.json").exists()


def test_unknown_skill_id_is_repaired_by_qwen(tmp_path: Path) -> None:
    stub = _Stub(
        _selection(selected="unknown-method"),
        _selection(),
        reasoning_text="先分类任务并逐项比较技能。" * 20,
    )

    artifact = run_system_plan_method_skill_selection(
        lineage_id="lineage-methodology-repair",
        task_signature={"stage": "research_opportunity_mapping"},
        skill_root=_skill_root(tmp_path),
        output_dir=tmp_path / "run",
        completion=stub,
    )

    assert artifact.selection.selected_skill_ids == (
        "sparse-dynamics-identification",
    )
    assert len(stub.calls) == 2
    assert "未知编号" in stub.calls[1]["messages"][0]["content"]


def test_short_method_prose_is_aggregated_into_actionable_retry(
    tmp_path: Path,
) -> None:
    invalid = _selection()
    invalid["task_classification"] = "过短"
    invalid["selection_rationale"] = "也过短"
    invalid["non_evidence_boundary"] = "仍过短"
    stub = _Stub(
        invalid,
        _selection(),
        reasoning_text="先分类任务并逐项比较技能。" * 20,
    )

    run_system_plan_method_skill_selection(
        lineage_id="lineage-methodology-length-repair",
        task_signature={"stage": "research_opportunity_mapping"},
        skill_root=_skill_root(tmp_path),
        output_dir=tmp_path / "run",
        completion=stub,
    )

    retry_instruction = stub.calls[1]["messages"][0]["content"]
    assert "任务分类至少需要20个字符" in retry_instruction
    assert "选择理由至少需要30个字符" in retry_instruction
    assert "非证据边界至少需要30个字符" in retry_instruction
