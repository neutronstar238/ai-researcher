"""grader 必须在中文下与英文下同等有效（`P-20260808-095`）。

缺陷是我造成的：模板与交付语言是中文，但撰写提示词与全部 grader 标记都留在英文。
后果有两层，且第二层更严重：

1. 可反驳性检查只认英文标记，所以一份合格的中文计划会被判"未声明反驳条件"而拒收。
   系统为通过自己的 grader，只能改用英文写作——文档里中文标题配英文正文正是这么来的，
   不是模型的选择。
2. 已达成结果检查的正则只认英文，所以中文里的越界宣称（"实验结果表明本方法优于基线"）
   反而检测不到。一个只在一种语言下生效的诚实性检查，等于在另一种语言下失效。

这与 `P-20260807-092` 同一缺陷类：grader 检的是词汇而非实质。这些测试把两种语言都钉住。
"""

from __future__ import annotations

from typing import Any

from autoresearch.competition.system_authored_plan import (
    _FALSIFIABILITY_MARKERS,
    guard_authored_plan,
)
from autoresearch.research.plans import ResearchPlan, ResearchPlanStatus


def _plan(**overrides: Any) -> ResearchPlan:
    payload: dict[str, Any] = {
        "project_id": "task-x",
        "candidate_id": "cand-x",
        "title": "受约束符号回归",
        "abstract": "背景、方法与预期结果的自足摘要。",
        "problem_statement": "上一条 lineage 的总体中位对数效应为 -0.8448548894388439。",
        "rationale": "失败机制是无约束搜索产生了未支持字段的方程因子。",
        "technical_details": "两阶段搜索：字段清单提取，然后受约束的符号回归。",
        "datasets": {"source": "冻结面板。", "target": "导数 NMSE。"},
        "methods": "先解析可用字段名，再只用白名单项生成候选方程。",
        "experiments": ["在 12 个系统上运行完整流程。", "消融白名单。", "敏感性分析。"],
        "baselines": ["调优后的符号回归基线"],
        "metrics": ["导数 NMSE"],
        "expected_results": (
            "预期总体中位对数效应超过 0.05129329438755058。"
            "若仍低于该阈值，则本假设被反驳；零结果同样是有效结果。"
        ),
        "code_agent_brief": "执行命令 python /harness/runner.py --spec x",
        "risks_and_alternatives": ["白名单可能过严，可退化为软惩罚。", "PDE 仅 2 个系统。"],
        "references": ["retained prior lineage package"],
        "evidence_refs": ["runs/x/y.json"],
        "status": ResearchPlanStatus.DRAFT,
    }
    payload.update(overrides)
    return ResearchPlan.model_validate(payload)


def _numbers() -> set[str]:
    return {"-0.8448548894388439", "0.05129329438755058", "12", "2"}


def test_中文可反驳表述被接受() -> None:
    """核心回归：中文计划必须能通过自己的可反驳性检查。"""

    report = guard_authored_plan(
        plan=_plan(),
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
    )
    assert report.states_falsifiable_expectation, report.findings


def test_英文可反驳表述仍被接受() -> None:
    """改成双语不能牺牲原有能力。"""

    plan = _plan(
        expected_results=(
            "I expect the median to exceed 0.05129329438755058. A result below that "
            "would refute the hypothesis; a null result is a valid outcome."
        )
    )
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
    )
    assert report.states_falsifiable_expectation, report.findings


def test_只描述成功的中文计划仍被拒() -> None:
    """双语化不能把检查变成橡皮图章。"""

    plan = _plan(
        expected_results="预期总体中位对数效应超过 0.05129329438755058，方法将全面胜出。"
    )
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
    )
    assert not report.states_falsifiable_expectation


def test_中文的已达成宣称被拦住() -> None:
    """此前只认英文，所以中文越界宣称能蒙混过关。"""

    plan = _plan(rationale="实验结果表明本方法优于基线，机制已被证实。")
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
    )
    assert not report.claims_no_unobserved_result
    assert any("achieved result" in f for f in report.findings)


def test_中文的合法预期表述不被误拦() -> None:
    """"预期优于基线"是正当的预期语气，不是已达成宣称。

    这是 `P-20260804-087` 的教训：把合法表述当违规拦下，会惩罚正确的写作。
    """

    plan = _plan(rationale="预期本方法优于基线，但该判断尚未经测量验证。")
    report = guard_authored_plan(
        plan=plan,
        evidence_numbers=_numbers(),
        cited_evidence=[],
        container_entry_points=("/harness/runner.py",),
    )
    assert report.claims_no_unobserved_result, report.findings


def test_标记表同时含中英条目() -> None:
    """结构性保证：任一语言缺失都会让该语言下的计划无法通过。"""

    assert any("refute" in m for m in _FALSIFIABILITY_MARKERS)
    assert any("反驳" in m for m in _FALSIFIABILITY_MARKERS)


# ---------------------------------------------------------------------------
# quality gate 必须看专用字段，并认中文词汇（`P-20260808-097`）
# ---------------------------------------------------------------------------


def test_基线写在_baselines_专用字段时门禁能看见() -> None:
    """真实缺陷：门禁只扫 methods/brief/experiments，漏看榜题要求的 `baselines` 字段。

    系统把基线正确写进 `baselines`，门禁却判"未指定基线"并拒收。检查漏看权威字段，
    比检查过严更糟：它惩罚的恰是按规范填写的计划。
    """

    from autoresearch.research.plans import audit_research_plan

    plan = _plan(
        methods="先解析可用字段名，再只用白名单项生成候选方程，评估导数 NMSE。",
        experiments=["在 12 个系统上运行完整流程。", "消融白名单。", "敏感性分析。"],
        baselines=["调优后的符号回归基线，运行于同一批冻结 cell"],
    )
    audit = audit_research_plan(plan)
    assert not any("baseline or control" in issue for issue in audit.issues), audit.issues


def test_中文基线一词被认可() -> None:
    """中文里"基线"最自然，原词表只认 baseline 与"对照"，恰好漏了它。"""

    from autoresearch.research.plans import audit_research_plan

    plan = _plan(
        methods="以调优后的符号回归作为基线，比较导数 NMSE。执行 python 脚本。",
        baselines=["基线：调优后的符号回归"],
    )
    audit = audit_research_plan(plan)
    assert not any("baseline or control" in issue for issue in audit.issues), audit.issues


def test_中文指标名被认可() -> None:
    """一份用中文命名指标的合格计划不该被判"未指定评估指标"。"""

    from autoresearch.research.plans import audit_research_plan

    plan = _plan(
        methods="以中位对数效应为主指标，辅以自助置信区间。执行 python 脚本。",
        metrics=["中位对数效应", "自助置信区间"],
        baselines=["基线：调优后的符号回归"],
    )
    audit = audit_research_plan(plan)
    assert not any("evaluation metrics" in issue for issue in audit.issues), audit.issues


def test_完全没有基线的计划仍被拒() -> None:
    """扩充词表不能把门禁变成橡皮图章。"""

    from autoresearch.research.plans import audit_research_plan

    plan = _plan(
        methods="直接运行方法并观察输出。执行 python 脚本。",
        experiments=["运行一次。", "再运行一次。", "第三次运行。"],
        baselines=[],
        metrics=["中位对数效应"],
    )
    audit = audit_research_plan(plan)
    assert any("baseline or control" in issue for issue in audit.issues)
