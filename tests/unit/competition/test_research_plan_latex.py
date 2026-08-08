"""《科学假设与研究计划》LaTeX 渲染器的测试。

这里守两条来源约束，它们比排版正确更重要：

1. **渲染器不代笔**。任何需要模型撰写的字段若为空，渲染必须失败，而不是填占位套话。
   一份含 agent 代笔句子的计划已经不是"系统自主产出"，这比缺一节更严重。
2. **虚构文献被拒**。榜题明令"严禁虚构"。提示词只是请求，所以必须有确定性检查：
   没有可核验 DOI/URL 的条目要在渲染前失败，而不是等人逐条去查。

另外测排版不改写内容：数值不许四舍五入，否则引文无法与证据比对。
"""

from __future__ import annotations

from typing import Any

import pytest

from autoresearch.competition.research_plan_latex import (
    ResearchPlanLatexError,
    assert_all_prose_is_authored,
    guard_references,
    render_research_plan_latex,
)


def _plan(**overrides: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "title": "Stratified Symbolic Regression for ODE/PDE Discovery",
        "abstract": "本文提出一种分层符号回归方法，背景是上一条 lineage 的总体中位对数效应为 -0.8448548894388439。",
        "problem_statement": "上一条 lineage 未通过 0.05129329438755058 的门禁。",
        "rationale": "失败机制是无约束搜索产生了未支持字段的方程因子。",
        "technical_details": "两阶段搜索：字段清单提取，然后受约束的符号回归。",
        "methods": "阶段一解析可用字段名；阶段二只用白名单项生成候选方程。",
        "experiments": ["实验一：在 12 个配对系统上运行完整流程。", "实验二：消融白名单约束。"],
        "baselines": ["operon_gp 调优后的符号回归基线"],
        "metrics": ["导数 NMSE", "paired_log_effect"],
        "expected_results": "预期总体中位对数效应超过 0.05129329438755058；若仍为负则假设被反驳。",
        "risks_and_alternatives": ["风险：白名单过严。备选：改为软惩罚。"],
        "datasets": {"source": "12 个配对系统的冻结面板。", "target": "导数 NMSE。"},
    }
    plan.update(overrides)
    return plan


def _refs() -> list[dict[str, Any]]:
    return [
        {
            "title": "Discovering governing equations from data by sparse identification",
            "authors": ["S. L. Brunton", "J. L. Proctor", "J. N. Kutz"],
            "venue": "PNAS",
            "publication_date": "2016-04-12",
            "doi": "10.1073/pnas.1517384113",
            "url": "https://www.pnas.org/doi/10.1073/pnas.1517384113",
            "retrieved_from": "openalex",
        }
    ]


# ---------------------------------------------------------------------------
# 约束一：渲染器不代笔
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "abstract",
        "problem_statement",
        "rationale",
        "technical_details",
        "methods",
        "expected_results",
    ],
)
def test_散文字段缺失时拒绝渲染(field: str) -> None:
    """宁可失败，也不能用占位文本伪装成完整计划。"""

    plan = _plan()
    plan[field] = ""
    with pytest.raises(ResearchPlanLatexError, match="必须由系统撰写"):
        render_research_plan_latex(plan=plan, references=_refs())


@pytest.mark.parametrize(
    "field", ["experiments", "baselines", "metrics", "risks_and_alternatives"]
)
def test_列表字段为空时拒绝渲染(field: str) -> None:
    plan = _plan()
    plan[field] = []
    with pytest.raises(ResearchPlanLatexError, match="必须由系统撰写"):
        render_research_plan_latex(plan=plan, references=_refs())


def test_数据集_source_或_target_缺失时拒绝渲染() -> None:
    plan = _plan(datasets={"source": "有", "target": ""})
    with pytest.raises(ResearchPlanLatexError, match="datasets.target"):
        render_research_plan_latex(plan=plan, references=_refs())


def test_错误信息列出所有缺失字段而不是只报第一个() -> None:
    """一次说清，避免作者反复试错。"""

    plan = _plan(abstract="", methods="")
    with pytest.raises(ResearchPlanLatexError) as excinfo:
        assert_all_prose_is_authored(plan)
    message = str(excinfo.value)
    assert "abstract" in message
    assert "methods" in message


# ---------------------------------------------------------------------------
# 约束二：虚构文献被拒
# ---------------------------------------------------------------------------


def test_没有_doi_和_url_的文献被拒() -> None:
    """这是"严禁虚构"的执行点：无法核验等同于虚构。"""

    bad = [{"title": "某篇看起来很像真的论文", "retrieved_from": "openalex"}]
    problems = guard_references(bad)
    assert problems
    assert any("没有可核验的 DOI 或 URL" in p for p in problems)


def test_未声明检索来源的文献被拒() -> None:
    """没有来源就无法区分"检索所得"与"模型自己写出来的"。"""

    bad = [{"title": "某论文", "doi": "10.1073/pnas.1517384113"}]
    problems = guard_references(bad)
    assert any("未声明检索来源" in p for p in problems)


def test_格式不合法的_doi_被拒() -> None:
    bad = [
        {"title": "某论文", "doi": "not-a-doi", "retrieved_from": "arxiv"}
    ]
    problems = guard_references(bad)
    assert any("没有可核验的 DOI 或 URL" in p for p in problems)


def test_空文献列表被拒() -> None:
    problems = guard_references([])
    assert problems
    assert "真实文献" in problems[0]


def test_合法文献通过检查() -> None:
    assert guard_references(_refs()) == []


def test_只有_url_没有_doi_的_arxiv_预印本可以通过() -> None:
    """arXiv 预印本常无 DOI，但有稳定 URL，属于可核验。"""

    refs = [
        {
            "title": "Some arXiv preprint",
            "url": "https://arxiv.org/abs/2301.00001",
            "retrieved_from": "arxiv",
        }
    ]
    assert guard_references(refs) == []


def test_严格模式下虚构文献导致渲染失败() -> None:
    with pytest.raises(ResearchPlanLatexError, match="严禁虚构"):
        render_research_plan_latex(
            plan=_plan(),
            references=[{"title": "无法核验的条目"}],
            strict_references=True,
        )


def test_非严格模式下文献缺口在文档内显著标注() -> None:
    """过渡期允许渲染，但不能静默放过——缺口要写进文档让读者看见。"""

    tex = render_research_plan_latex(
        plan=_plan(), references=[], strict_references=False
    )
    assert "参考文献缺失" in tex
    assert "textcolor{red}" in tex


# ---------------------------------------------------------------------------
# 排版：结构对齐榜题，内容不被改写
# ---------------------------------------------------------------------------


def test_章节结构对齐榜题要求() -> None:
    tex = render_research_plan_latex(plan=_plan(), references=_refs())
    for heading in (
        r"\section*{摘要}",
        r"\section{待研究问题}",
        r"\section{解决思路}",
        r"\section{必要的技术手段}",
        r"\section{数据集}",
        r"\section{方法论}",
        r"\section{实验设计}",
        r"\section{实验结果}",
        r"\section{参考论文}",
    ):
        assert heading in tex, heading
    # 对照基线与评估指标必须是独立中文小节，榜题点名要求。
    assert r"\subsection{对照基线}" in tex
    assert r"\subsection{评估指标}" in tex


def test_数值不被改写() -> None:
    """四舍五入会让引文无法与证据比对。"""

    tex = render_research_plan_latex(plan=_plan(), references=_refs())
    assert "-0.8448548894388439" in tex
    assert "0.05129329438755058" in tex


def test_模型原文一字不改地出现() -> None:
    tex = render_research_plan_latex(plan=_plan(), references=_refs())
    assert "失败机制是无约束搜索产生了未支持字段的方程因子。" in tex
    assert "实验一：在 12 个配对系统上运行完整流程。" in tex
    assert "operon_gp" in tex.replace(r"\_", "_")


def test_latex_特殊字符被转义() -> None:
    """未转义的下划线或 & 会让编译失败，等于产出不可用。"""

    plan = _plan(methods="使用 term_support_f1 与 100% 覆盖率，A&B 对比，成本 $5。")
    tex = render_research_plan_latex(plan=plan, references=_refs())
    assert r"term\_support\_f1" in tex
    assert r"100\%" in tex
    assert r"A\&B" in tex
    assert r"\$5" in tex


def test_溯源表包含哈希并声明零人工撰写() -> None:
    tex = render_research_plan_latex(
        plan=_plan(),
        references=_refs(),
        plan_hash="a" * 64,
        artifact_hash="b" * 64,
        lineage_id="task2699-lineage-v2",
        model_name="qwen3.7-max",
    )
    assert "a" * 64 in tex
    assert "b" * 64 in tex
    assert "task2699-lineage-v2" in tex
    assert "人工撰写散文字段数" in tex


def test_参考文献渲染为可点击并标注检索来源() -> None:
    tex = render_research_plan_latex(plan=_plan(), references=_refs())
    assert "10.1073/pnas.1517384113" in tex
    assert "检索来源：openalex" in tex
    assert r"\href{https://doi.org/" in tex


def test_未执行时实验结果一节如实说明而不是留白() -> None:
    """留白会让读者以为漏排；写成"已完成"则是谎报。"""

    tex = render_research_plan_latex(plan=_plan(), references=_refs())
    assert "尚未执行" in tex


def test_已有实测结果时原样呈现() -> None:
    plan = _plan(results="总体中位对数效应 -0.6859100612592094，门禁未通过。")
    tex = render_research_plan_latex(plan=plan, references=_refs())
    assert "-0.6859100612592094" in tex
    assert "尚未执行" not in tex


def test_文档是完整可编译骨架() -> None:
    tex = render_research_plan_latex(plan=_plan(), references=_refs())
    assert tex.count(r"\begin{document}") == 1
    assert tex.count(r"\end{document}") == 1
    assert r"\documentclass[12pt,a4paper]{ctexart}" in tex
    # 环境必须配对，否则编译失败。
    for env in ("tabularx", "enumerate", "itemize"):
        assert tex.count(rf"\begin{{{env}}}") == tex.count(rf"\end{{{env}}}"), env


# ---------------------------------------------------------------------------
# 长数字防断行（`P-20260808-096`）
# ---------------------------------------------------------------------------


def test_长数字被包进_mbox_以禁止断行() -> None:
    """`1000000000000.0` 曾被 LaTeX 在数字中间断行，页面出现残缺的
    `000000000000.0)`，读者会误读成另一个数值。"""

    plan = _plan(
        technical_details="失败 cell 的损失被封顶为 1000000000000.0，属基础设施上限。"
    )
    tex = render_research_plan_latex(plan=plan, references=_refs())
    assert r"\mbox{1000000000000.0}" in tex


def test_防断行不改写数值本身() -> None:
    """排版可以调整，数值不能。改写会破坏引文与证据的比对。"""

    plan = _plan(problem_statement="总体中位对数效应为 -0.8448548894388439。")
    tex = render_research_plan_latex(plan=plan, references=_refs())
    assert "-0.8448548894388439" in tex
    # 包裹后原数值仍完整可见，没有被科学计数法或四舍五入替代。
    assert "8448548894388439" in tex
    assert "-8.4e-01" not in tex


def test_短数字不必包裹以免噪声() -> None:
    """把每个数字都包起来会让源文件难读，且无必要。"""

    plan = _plan(methods="共 12 个系统，其中 2 个属 PDE。")
    tex = render_research_plan_latex(plan=plan, references=_refs())
    assert r"\mbox{12}" not in tex
    assert "12 个系统" in tex


def test_模板声明长标识符断行支持() -> None:
    """overall_median_log_effect 这类名字若不能在下划线处换行会溢出版心。"""

    tex = render_research_plan_latex(plan=_plan(), references=_refs())
    assert "seqsplit" in tex
    assert r"\do\_" in tex or r"\do_" in tex
