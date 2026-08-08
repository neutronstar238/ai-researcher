"""研究计划 Markdown 渲染器的测试。

渲染器是派生视图，所以它必须满足两类性质：

1. **不失真**：JSON 里的每个字段都要在 Markdown 里出现。一个静默吞掉字段的渲染器会让
   读者误以为计划里没有那部分内容，这比不渲染更糟。
2. **不越权**：渲染器不得引入 JSON 里没有的内容，也不得改写模型写的散文。它只重排版。

同时要携带 `plan_hash`，否则读者无法判断手上这份 Markdown 对应哪份不可变字节。
"""

from __future__ import annotations

from typing import Any

import pytest

from autoresearch.competition.research_plan_markdown import (
    render_outcome_markdown,
    render_plan_artifact_markdown,
    render_research_plan_markdown,
)


def _plan() -> dict[str, Any]:
    return {
        "title": "分层符号回归",
        "project_id": "task2699-lineage-v2",
        "id": "plan_abc123",
        "candidate_id": "candidate_764f851f5830",
        "status": "ready_for_approval",
        "approval_status": "pending",
        "validation_status": "passed",
        "created_at": "2026-08-07T09:59:17.439020Z",
        "updated_at": "2026-08-07T09:59:17.439020Z",
        "problem_statement": "上一条 lineage 的总体中位对数效应为 -0.8448548894388439。",
        "rationale": "失败机制是无约束搜索产生了未支持字段的方程因子。",
        "methods": "阶段一：解析可用字段名。阶段二：只用白名单项生成候选方程。",
        "technical_details": "两阶段搜索：字段清单提取，然后受约束的符号回归。",
        "experiments": [
            "实验一：在全部 12 个配对系统上运行完整候选流程。",
            "实验二：在 3 个 ODE 系统上做消融。",
        ],
        "expected_results": "预期总体中位对数效应超过 0.05129329438755058。若仍低于该阈值则假设被反驳。",
        "risks_and_alternatives": ["风险：白名单可能过严。备选：改为软惩罚。"],
        "datasets": {
            "source": "12 个配对系统的冻结面板。",
            "target": "导数 NMSE。",
        },
        "references": ["上一条 lineage task2696。"],
        "evidence_refs": ["runs/manual-live/task2696/full-results.json"],
        "code_agent_brief": "python /harness/runner.py --config x",
        "metadata": {},
        "quality_gate": {
            "passed": True,
            "score": 0.98,
            "verdict": "passed",
            "issues": [],
            "warnings": ["expected_results 应区分预期与观测"],
            "rubric_scores": {"scientific_value": 39.2, "technical_depth": 29.4},
        },
    }


def test_每个计划字段都出现在渲染结果中() -> None:
    """不失真：静默丢字段比不渲染更糟。"""

    plan = _plan()
    text = render_research_plan_markdown(plan=plan, plan_hash="a" * 64)

    # 散文字段的内容必须原样出现。
    assert "上一条 lineage 的总体中位对数效应为 -0.8448548894388439。" in text
    assert "失败机制是无约束搜索产生了未支持字段的方程因子。" in text
    assert "阶段一：解析可用字段名。" in text
    assert "两阶段搜索：字段清单提取，然后受约束的符号回归。" in text
    # 列表字段的每一项都要出现。
    assert "实验一：在全部 12 个配对系统上运行完整候选流程。" in text
    assert "实验二：在 3 个 ODE 系统上做消融。" in text
    assert "风险：白名单可能过严。备选：改为软惩罚。" in text
    # 字典字段的每个键值都要出现。
    assert "12 个配对系统的冻结面板。" in text
    assert "导数 NMSE。" in text
    # 元数据。
    assert "task2699-lineage-v2" in text
    assert "plan_abc123" in text


def test_数字不被改写() -> None:
    """渲染器不得对数值做四舍五入，否则引文无法与证据比对。"""

    plan = _plan()
    text = render_research_plan_markdown(plan=plan, plan_hash="b" * 64)
    assert "-0.8448548894388439" in text
    assert "0.05129329438755058" in text


def test_头部携带哈希与溯源声明() -> None:
    """读者必须能判断手上这份 Markdown 对应哪份不可变字节。"""

    text = render_research_plan_markdown(
        plan=_plan(),
        plan_hash="c" * 64,
        artifact_hash="d" * 64,
        lineage_id="task2699-lineage-v2",
        model_name="qwen3.7-max",
        authoring_attempts=1,
        reasoning_tokens=4000,
    )
    assert "c" * 64 in text
    assert "d" * 64 in text
    assert "qwen3.7-max" in text
    # 必须声明 JSON 是权威，否则 Markdown 可能被误当成凭证。
    assert "以 JSON 为准" in text
    assert "由系统（模型）撰写" in text
    assert "人工撰写的散文字段数：0" in text


def test_未识别的字段落到兜底节而不是被丢弃() -> None:
    """schema 演进时新增字段不得从读者视野里消失。"""

    plan = _plan()
    plan["some_future_field"] = "这是一个渲染器还不认识的新字段"
    text = render_research_plan_markdown(plan=plan, plan_hash="e" * 64)
    assert "其他字段" in text
    assert "some_future_field" in text
    assert "这是一个渲染器还不认识的新字段" in text


def test_质量门禁单独成节且标注分数() -> None:
    text = render_research_plan_markdown(plan=_plan(), plan_hash="f" * 64)
    assert "## 质量门禁" in text
    assert "0.98" in text
    assert "expected_results 应区分预期与观测" in text


def test_空字段与缺失字段不会让渲染崩溃() -> None:
    """一份刚生成、部分字段为空的计划也要能渲染出来给人看。"""

    sparse: dict[str, Any] = {"title": "最小计划", "problem_statement": ""}
    text = render_research_plan_markdown(plan=sparse)
    assert "最小计划" in text
    assert "（空）" in text


def test_从_artifact_payload_渲染时自动带上溯源() -> None:
    artifact = {
        "lineage_id": "task2699-lineage-v2",
        "plan": _plan(),
        "plan_hash": "1" * 64,
        "artifact_hash": "2" * 64,
        "model_name": "qwen3.7-max",
        "authoring_attempts": 2,
        "reasoning_tokens": 2090,
    }
    text = render_plan_artifact_markdown(artifact)
    assert "1" * 64 in text
    assert "2" * 64 in text
    assert "撰写尝试次数：2" in text


def test_缺少_plan_字典时明确报错() -> None:
    """错误要说清楚，而不是渲染出一份空文档让读者以为计划是空的。"""

    with pytest.raises(ValueError, match="缺少 plan 字典"):
        render_plan_artifact_markdown({"plan_hash": "3" * 64})


# ---------------------------------------------------------------------------
# 结果解读（outcome）的渲染
# ---------------------------------------------------------------------------


def _outcome(*, accepted: bool = True) -> dict[str, Any]:
    return {
        "lineage_id": "task2699-system-authored-lineage-v2",
        "accepted": accepted,
        "frozen_gate_passed": False,
        "verdict_consistent_with_gate": True,
        "outcome_hash": "9" * 64,
        "package_hash": "8" * 64,
        "model_name": "qwen3.7-max",
        "reasoning_tokens": 2090,
        "hand_written_prose_count": 0,
        "refusal_reasons": [] if accepted else ["counter-reading 没有反驳结论"],
        "traceability": {
            "checked_number_count": 30,
            "traceable_number_count": 30,
            "untraceable_numbers": [],
            "passed": True,
        },
        "relation_audit": {
            "checked_relation_count": 3,
            "contradictions": [],
            "passed": True,
            "audit_hash": "7" * 64,
        },
        "interpretation": {
            "verdict": "claim_not_supported",
            "what_the_evidence_supports": "候选方法未优于 baseline，总体中位对数效应 -0.6859100612592094。",
            "what_the_evidence_does_not_support": "证据不支持任何改进主张。",
            "strongest_counter_reading": "PDE 层中位数由 reaction_diffusion_cylinder 的单次失败主导。",
            "limitations": ["仅测试了 2 个 PDE 系统。", "损失上限 1e12 可能掩盖更差表现。"],
        },
    }


def test_结果解读渲染包含判定与门禁一致性() -> None:
    """判定与门禁是否一致是这份文档最要紧的信息。"""

    text = render_outcome_markdown(_outcome())
    assert "结论不成立" in text  # claim_not_supported 的中文标签
    assert "未通过" in text  # frozen_gate_passed=False
    assert "一致" in text
    assert "30/30" in text
    assert "数值关系复算 | 通过（复算 3 项）" in text


def test_结果解读渲染保留模型原文与数字() -> None:
    text = render_outcome_markdown(_outcome())
    assert "-0.6859100612592094" in text
    assert "PDE 层中位数由 reaction_diffusion_cylinder 的单次失败主导。" in text
    assert "仅测试了 2 个 PDE 系统。" in text
    assert "1e12" in text


def test_被拒收的解读必须显示拒收理由() -> None:
    """拒收信息不能被隐藏，否则读者会以为这份解读已被接受。"""

    text = render_outcome_markdown(_outcome(accepted=False))
    assert "拒收" in text
    assert "counter-reading 没有反驳结论" in text


def test_无法溯源的数字被显著标出() -> None:
    """编造的数字是最严重的问题，必须单独成节。"""

    payload = _outcome()
    payload["traceability"]["untraceable_numbers"] = ["-0.99"]
    payload["traceability"]["traceable_number_count"] = 29
    payload["traceability"]["passed"] = False
    text = render_outcome_markdown(payload)
    assert "无法溯源的数字" in text
    assert "-0.99" in text
    assert "29/30" in text


def test_算术矛盾被显著标出() -> None:
    payload = _outcome(accepted=False)
    payload["relation_audit"]["passed"] = False
    payload["relation_audit"]["contradictions"] = ["0.0468 < 0.0 is false"]
    text = render_outcome_markdown(payload)
    assert "存在算术矛盾" in text
    assert "算术矛盾" in text
    assert "0.0468 < 0.0 is false" in text


def test_结果解读缺少_interpretation_时明确报错() -> None:
    with pytest.raises(ValueError, match="缺少 interpretation 字典"):
        render_outcome_markdown({"outcome_hash": "7" * 64})
