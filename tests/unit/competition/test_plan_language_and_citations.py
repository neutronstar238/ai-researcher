"""交付语言与行内引用的 grader 测试（`P-20260808-095`）。

v7 产出的《科学假设与研究计划》有三个缺陷，全部是设计错误而非模型能力问题：

1. **中英混杂**：章节标题中文、正文英文。根因是从未有检查要求中文，而可反驳性标记
   原本只有英文——系统若用中文写就永远过不了自己的 grader，只能用英文写。
2. **参考文献是装饰**：列了 7 条，正文零引用。根因是顺序做反了，先写计划再检索，
   计划不可能引用它还没见过的文献。
3. **像工单不像研究计划**：满篇 lineage id 与 ledger 字段名，外部读者无法核验。

这些测试把修复固定住：语言与引用成为确定性检查，而不是提示词里的请求。
"""

from __future__ import annotations

from typing import Any

from autoresearch.competition.system_authored_plan import (
    _FALSIFIABILITY_MARKERS,
    _chinese_character_ratio,
    guard_authored_plan,
)
from autoresearch.schemas import ResearchPlan


def _plan(**overrides: Any) -> ResearchPlan:
    payload: dict[str, Any] = {
        "project_id": "task-x",
        "candidate_id": "cand-x",
        "title": "Constrained Symbolic Regression for Governing Equation Discovery",
        "abstract": (
            "稀疏回归方法在含噪测量数据上难以稳定恢复控制方程[1]。本文提出以物理可观测量"
            "约束搜索空间的符号回归方法，并在生成阶段强制项支撑唯一性。预期总体中位对数"
            "效应超过 0.05129329438755058；若低于该阈值则本假设被反驳，零结果同样是有效结果。"
        ),
        "problem_statement": (
            "既有稀疏辨识方法在噪声条件下会引入不存在的字段项[1]，导致方程无法通过契约"
            "校验。本研究要解决的是搜索空间无约束带来的无效项问题。"
        ),
        "rationale": (
            "先前工作表明，把物理先验注入符号回归可以显著缩小搜索空间[2]。据此推断，"
            "以查询时间序列中可观测的量为基函数库，可在生成阶段就排除无效字段。"
        ),
        "technical_details": (
            "两阶段流程：先从查询元数据提取可用字段清单，再在受限词表内做稀疏回归。"
            "每个 cell 的墙钟上限为 300 秒，内存上限 4096 MB。"
        ),
        "methods": (
            "采用受约束的符号回归，并以弹性网正则化抑制过拟合[2]。聚合方式为先在系统内"
            "对条件与随机种子取中位数，再跨系统取中位数。"
        ),
        "experiments": [
            "在 10 个 ODE 系统上运行完整流程，度量导数 NMSE。",
            "在 2 个 PDE 系统上运行，重点关注此前完全失败的系统。",
            "消融实验：对比受约束与无约束搜索空间。",
        ],
        "baselines": ["调优后的 operon_gp 符号回归基线"],
        "metrics": ["导数 NMSE", "配对对数效应 paired_log_effect"],
        "expected_results": (
            "预期总体中位对数效应超过 0.05129329438755058。若仍低于该阈值，"
            "或任一层中位数为负，则本假设被反驳；零结果同样是有效结果并将如实报告。"
        ),
        "code_agent_brief": (
            "运行命令 python /harness/runner.py --config constrained_sr 执行评估。"
            "required_method_tokens=[constrained, sparse]"
        ),
        "risks_and_alternatives": [
            "风险：受限词表可能过严，排除必要的复合项。备选：改为软惩罚。",
            "风险：PDE 层仅 2 个系统，中位数对单点失败敏感。备选：报告为覆盖缺口。",
        ],
        "references": ["retained prior lineage package"],
        "evidence_refs": ["runs/manual-live/x/package.json"],
        "datasets": {
            "source": "12 个配对系统的冻结面板，含干净与含噪两种条件。",
            "target": "导数 NMSE 的留出切分。",
        },
    }
    payload.update(overrides)
    return ResearchPlan.model_validate(payload)


def _numbers() -> set[str]:
    return {"0.05129329438755058", "300", "4096", "10", "2", "12"}


# ---------------------------------------------------------------------------
# 中文字符占比
# ---------------------------------------------------------------------------


def test_中文占比忽略英文标识符() -> None:
    """一份中文技术文档本就含大量英文标识符，不该因此被判成英文。"""

    text = "本方法要求 term_support_f1_minimum 等于 1.0，并在 reaction_diffusion_cylinder 上验证。"
    assert _chinese_character_ratio(text) >= 0.55


def test_纯英文散文被判定为不达标() -> None:
    text = "The previous lineage produced an overall median log effect of -0.68."
    assert _chinese_character_ratio(text) < 0.55


def test_无字母无汉字时不误判() -> None:
    """纯数字或纯标点不该被当成英文。"""

    assert _chinese_character_ratio("1.0 / 2.0 == 0.5") == 1.0


# ---------------------------------------------------------------------------
# 语言 grader
# ---------------------------------------------------------------------------


def test_中文计划通过语言检查() -> None:
    report = guard_authored_plan(
        plan=_plan(),
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        literature_count=2,
        require_chinese=True,
    )
    language_findings = [f for f in report.findings if "简体中文" in f]
    assert not language_findings, report.findings


def test_英文正文被语言检查拒收并点名字段() -> None:
    """拒收必须说清是哪些字段，否则作者只能猜。"""

    plan = _plan(
        problem_statement=(
            "The previous lineage produced an overall median log effect of "
            "-0.6859100612592094, failing the minimum gate[1]."
        )
    )
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers() | {"-0.6859100612592094"},
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        literature_count=2,
        require_chinese=True,
    )
    hits = [f for f in report.findings if "简体中文" in f]
    assert hits
    assert "problem_statement" in hits[0]


def test_未开启中文要求时不检查语言() -> None:
    """既有英文 lineage 必须仍能通过，否则留存证据会失效。"""

    plan = _plan(problem_statement="An English problem statement citing prior work[1].")
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        literature_count=2,
        require_chinese=False,
    )
    assert not [f for f in report.findings if "简体中文" in f]


# ---------------------------------------------------------------------------
# 行内引用 grader
# ---------------------------------------------------------------------------


def test_带引用的计划通过引用检查() -> None:
    report = guard_authored_plan(
        plan=_plan(),
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        literature_count=2,
        require_chinese=True,
    )
    assert not [f for f in report.findings if "行内引用" in f]


def test_缺少行内引用被拒收() -> None:
    """这是 v7 的真实缺陷：文献列了却零引用。"""

    plan = _plan(
        problem_statement="既有方法在噪声条件下会引入不存在的字段项，导致校验失败。",
        rationale="据此推断，以可观测量为基函数库可排除无效字段。",
        methods="采用受约束的符号回归，聚合方式为先系统内取中位数再跨系统取中位数。",
    )
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        literature_count=2,
        require_chinese=True,
    )
    hits = [f for f in report.findings if "行内引用" in f]
    assert hits
    for field in ("problem_statement", "rationale", "methods"):
        assert field in hits[0]


def test_超范围的引用编号被拒收() -> None:
    """超范围编号等同于虚构引用，必须拦下。"""

    plan = _plan(
        problem_statement="既有方法会引入不存在的字段项[9]，导致契约校验失败。"
    )
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        literature_count=2,
        require_chinese=True,
    )
    hits = [f for f in report.findings if "超出已调研文献范围" in f]
    assert hits
    assert "9" in hits[0]


def test_没有文献时不强制引用() -> None:
    """文献调研未接入时不该反过来卡住计划撰写。"""

    plan = _plan(
        problem_statement="既有方法在噪声条件下会引入不存在的字段项，导致校验失败。",
        rationale="据此推断，以可观测量为基函数库可排除无效字段。",
        methods="采用受约束的符号回归。",
    )
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        literature_count=0,
        require_chinese=True,
    )
    assert not [f for f in report.findings if "行内引用" in f]


# ---------------------------------------------------------------------------
# 可反驳性：中文表达必须与英文等效
# ---------------------------------------------------------------------------


def test_中文可反驳性表达被识别() -> None:
    """这是语言混杂的根因：标记原本只有英文，中文计划永远过不了自己的 grader。"""

    for phrasing in (
        "若低于该阈值则本假设被反驳",
        "零结果同样是有效结果",
        "该结果将推翻本文的机制假设",
        "若未观测到改进，则说明假设不成立",
    ):
        assert any(
            marker in phrasing for marker in _FALSIFIABILITY_MARKERS
        ), phrasing


def test_中文计划的可反驳性检查通过() -> None:
    report = guard_authored_plan(
        plan=_plan(),
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
        literature_count=2,
        require_chinese=True,
    )
    assert report.states_falsifiable_expectation
