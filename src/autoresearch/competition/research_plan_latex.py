"""把系统撰写的研究计划渲染成《科学假设与研究计划》LaTeX 文档。

模板与内容的边界
----------------
本模块只提供**排版模板**：文档类、字体、页面、章节标题、三线表、参考文献编号格式。
这些是格式要求，由本文件固定，落地后不再改动。

模板之外的每一个字，都必须来自系统（模型）。渲染器不撰写、不总结、不改写、不补全。
它拿到什么就排什么。这条边界由 `assert_all_prose_is_authored` 在渲染前强制：任何
需要模型撰写的字段若为空，渲染直接拒绝，而不是填一句占位的套话。原因是一份含有
agent 代笔句子的计划，已经不再是"系统自主产出"，这比缺一节更严重。

章节结构对齐榜题《生成结果规范》
--------------------------------
待研究问题、解决思路、必要的技术手段、数据集（Source/Target）、标题、摘要、方法论、
实验设计（含 Baselines 与 Metrics）、实验结果、参考论文。

参考文献必须真实
----------------
榜题明令"严禁虚构"。仅靠提示词要求模型别编造是不够的：提示词是请求，不是保证。
所以参考文献走 `LiteratureReference`，每条都要带可核验的 DOI 或 URL，并声明检索来源
（arxiv / openalex）与检索时间。缺少可核验标识的条目会被 `guard_references` 拒收，
让编造在渲染前就失败，而不是等人去逐条查。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# 需要模型撰写的散文字段。任一为空则拒绝渲染，绝不由渲染器代笔。
_REQUIRED_AUTHORED_FIELDS: tuple[str, ...] = (
    "title",
    "abstract",
    "problem_statement",
    "rationale",
    "technical_details",
    "methods",
    "expected_results",
)

# 需要模型撰写的列表字段，同样不得为空。
_REQUIRED_AUTHORED_LISTS: tuple[str, ...] = (
    "experiments",
    "baselines",
    "metrics",
    "risks_and_alternatives",
)


class ResearchPlanLatexError(RuntimeError):
    """当计划无法在不代笔的前提下渲染时抛出。"""


def _tex_escape(text: Any) -> str:
    """转义 LaTeX 特殊字符。

    只做转义，不改写内容。反斜杠必须先处理，否则后续替换插入的反斜杠会被二次转义。
    """

    if text is None:
        return ""
    out = str(text)
    out = out.replace("\\", r"\textbackslash{}")
    for char, repl in (
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ):
        out = out.replace(char, repl)
    return out


def assert_all_prose_is_authored(plan: Mapping[str, Any]) -> None:
    """渲染前强制：所有散文字段都必须由系统撰写过。

    这不是数据校验，而是一条来源约束。渲染器宁可失败，也不能用占位文本把一份不完整的
    计划伪装成完整的——那会让"系统自主产出"这句话失去意义。
    """

    missing: list[str] = []
    for field in _REQUIRED_AUTHORED_FIELDS:
        value = plan.get(field)
        if not isinstance(value, str) or not value.strip():
            missing.append(field)
    for field in _REQUIRED_AUTHORED_LISTS:
        value = plan.get(field)
        if not isinstance(value, (list, tuple)) or not value:
            missing.append(field)
    source = (plan.get("datasets") or {}).get("source") if isinstance(
        plan.get("datasets"), Mapping
    ) else None
    target = (plan.get("datasets") or {}).get("target") if isinstance(
        plan.get("datasets"), Mapping
    ) else None
    if not (isinstance(source, str) and source.strip()):
        missing.append("datasets.source")
    if not (isinstance(target, str) and target.strip()):
        missing.append("datasets.target")

    if missing:
        raise ResearchPlanLatexError(
            "以下字段必须由系统撰写后才能渲染，渲染器不会代笔填充："
            + "、".join(missing)
        )


_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")


def guard_references(references: Sequence[Mapping[str, Any]]) -> list[str]:
    """检查参考文献是否可核验。返回问题列表，空列表表示通过。

    榜题明令"严禁虚构"。一条无法核验的引文，与编造的引文在读者那里是同一回事，
    所以这里要求每条至少有一个可解析的 DOI 或 http(s) URL，并且声明检索来源。
    """

    problems: list[str] = []
    if not references:
        return ["参考文献为空；榜题要求给出系统生成假设所引用的真实文献列表"]

    for index, ref in enumerate(references, 1):
        title = str(ref.get("title") or "").strip()
        if not title:
            problems.append(f"第 {index} 条缺少标题")
        doi = str(ref.get("doi") or "").strip().lower()
        doi = doi.removeprefix("https://doi.org/").removeprefix("doi:")
        url = str(ref.get("url") or "").strip()
        has_doi = bool(doi) and bool(_DOI_PATTERN.match(doi))
        has_url = url.startswith("http://") or url.startswith("https://")
        if not (has_doi or has_url):
            problems.append(
                f"第 {index} 条（{title[:48] or '无标题'}）没有可核验的 DOI 或 URL，"
                "无法确认它不是虚构的"
            )
        retrieved_from = str(ref.get("retrieved_from") or "").strip()
        if not retrieved_from:
            problems.append(
                f"第 {index} 条（{title[:48] or '无标题'}）未声明检索来源，"
                "无法追溯它是检索所得还是模型自行写出"
            )
    return problems


def _render_reference(ref: Mapping[str, Any]) -> str:
    """按 GB/T 7714 风格渲染一条参考文献，保留可点击的 DOI/URL。"""

    authors = ref.get("authors")
    if isinstance(authors, (list, tuple)) and authors:
        names = [str(a).strip() for a in authors if str(a).strip()]
        if len(names) > 3:
            author_text = _tex_escape("，".join(names[:3])) + r", 等"
        else:
            author_text = _tex_escape("，".join(names))
    else:
        author_text = r"\textit{作者信息缺失}"

    parts = [author_text, _tex_escape(ref.get("title"))]
    venue = str(ref.get("venue") or "").strip()
    if venue:
        parts.append(_tex_escape(venue))
    date = str(ref.get("publication_date") or "").strip()
    if date:
        parts.append(_tex_escape(date))
    line = ". ".join(p for p in parts if p)

    doi = str(ref.get("doi") or "").strip()
    url = str(ref.get("url") or "").strip()
    if doi:
        clean = doi.removeprefix("https://doi.org/").removeprefix("doi:")
        line += r". DOI: \href{https://doi.org/" + clean + "}{" + _tex_escape(clean) + "}"
    elif url.startswith(("http://", "https://")):
        line += r". \url{" + url + "}"

    retrieved_from = str(ref.get("retrieved_from") or "").strip()
    if retrieved_from:
        line += r" \textcolor{planmuted}{[检索来源：" + _tex_escape(retrieved_from) + "]}"
    return line


def _itemize(items: Sequence[Any], *, ordered: bool = False) -> str:
    env = "enumerate" if ordered else "itemize"
    if not items:
        # 到这一步不该为空（已被 assert 拦下），但仍不编造内容。
        body = r"\item \textit{（系统未提供内容）}"
    else:
        body = "\n".join(rf"\item {_tex_escape(item)}" for item in items)
    return f"\\begin{{{env}}}\n{body}\n\\end{{{env}}}"


# ---------------------------------------------------------------------------
# 模板本体。这部分是格式，落地后固定。
# ---------------------------------------------------------------------------

_PREAMBLE = r"""\documentclass[12pt,a4paper]{ctexart}

% ===== 页面与字体：对齐清华本科毕业论文排版惯例 =====
\usepackage[top=3.0cm,bottom=2.5cm,left=3.0cm,right=2.5cm]{geometry}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage{xcolor}
\usepackage{titlesec}
\usepackage[hidelinks]{hyperref}
\usepackage{url}

\definecolor{planblue}{HTML}{155A8A}
\definecolor{planmuted}{HTML}{6B7A86}
\hypersetup{colorlinks=true, linkcolor=planblue, urlcolor=planblue,
            citecolor=planblue}

% 章节标题：一级黑体小三，二级黑体四号
\ctexset{
  section/format = {\heiti\zihao{-3}\raggedright},
  section/aftername = \quad,
  subsection/format = {\heiti\zihao{4}\raggedright},
  subsection/aftername = \quad,
}

\linespread{1.5}
\setlength{\parindent}{2em}
\setlist[itemize]{leftmargin=2em, itemsep=0.2em, parsep=0.2em}
\setlist[enumerate]{leftmargin=2em, itemsep=0.2em, parsep=0.2em}
\setlength{\emergencystretch}{3em}
\sloppy

\pagestyle{fancy}
\fancyhf{}
\chead{\songti\zihao{5} 科学假设与研究计划}
\cfoot{\songti\zihao{5}\thepage}
\renewcommand{\headrulewidth}{0.4pt}
"""


def render_research_plan_latex(
    *,
    plan: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]] = (),
    plan_hash: str | None = None,
    artifact_hash: str | None = None,
    lineage_id: str | None = None,
    model_name: str | None = None,
    strict_references: bool = True,
) -> str:
    """渲染《科学假设与研究计划》。

    `plan` 的每个散文字段都必须已由系统撰写；`references` 必须是检索所得的真实文献。
    `strict_references=False` 只用于尚未接入检索的过渡期，会在文档内显著标注缺口，
    而不是静默放过。
    """

    assert_all_prose_is_authored(plan)

    ref_problems = guard_references(references)
    if ref_problems and strict_references:
        raise ResearchPlanLatexError(
            "参考文献未通过可核验检查（榜题严禁虚构）：" + "；".join(ref_problems)
        )

    datasets = plan.get("datasets") or {}
    body: list[str] = [_PREAMBLE]

    body.append(
        r"""
\begin{document}

\begin{center}
{\heiti\zihao{2} """
        + _tex_escape(plan.get("title"))
        + r"""}\\[1.2em]
{\songti\zihao{4} 科学假设与研究计划}\\[0.6em]
{\songti\zihao{5} 本文档由自动化研究系统自主生成}\\[0.4em]
{\songti\zihao{5}\today}
\end{center}

\vspace{0.8em}
"""
    )

    # 溯源表：读者在读任何结论前，先知道这份文档对应哪份不可变字节。
    prov_rows: list[str] = []
    if lineage_id:
        prov_rows.append(rf"lineage & \texttt{{{_tex_escape(lineage_id)}}} \\")
    if model_name:
        prov_rows.append(rf"撰写模型 & \texttt{{{_tex_escape(model_name)}}} \\")
    if plan_hash:
        prov_rows.append(
            rf"plan\_hash & \texttt{{\footnotesize {_tex_escape(plan_hash)}}} \\"
        )
    if artifact_hash:
        prov_rows.append(
            rf"artifact\_hash & \texttt{{\footnotesize {_tex_escape(artifact_hash)}}} \\"
        )
    prov_rows.append(r"人工撰写散文字段数 & 0 \\")
    body.append(
        r"""
\begin{center}
\begin{tabularx}{0.92\linewidth}{@{}lX@{}}
\toprule
"""
        + "\n".join(prov_rows)
        + r"""
\bottomrule
\end{tabularx}
\end{center}

\vspace{0.5em}
"""
    )

    body.append(r"\section*{摘要}" + "\n")
    body.append(_tex_escape(plan.get("abstract")) + "\n")

    body.append(r"\section{待研究问题}" + "\n")
    body.append(_tex_escape(plan.get("problem_statement")) + "\n")

    body.append(r"\section{解决思路}" + "\n")
    body.append(_tex_escape(plan.get("rationale")) + "\n")

    body.append(r"\section{必要的技术手段}" + "\n")
    body.append(_tex_escape(plan.get("technical_details")) + "\n")

    body.append(r"\section{数据集}" + "\n")
    body.append(
        r"""\begin{tabularx}{\linewidth}{@{}lX@{}}
\toprule
\textbf{Source} & """
        + _tex_escape(datasets.get("source"))
        + r""" \\
\midrule
\textbf{Target} & """
        + _tex_escape(datasets.get("target"))
        + r""" \\
\bottomrule
\end{tabularx}
"""
    )

    body.append(r"\section{方法论}" + "\n")
    body.append(_tex_escape(plan.get("methods")) + "\n")

    body.append(r"\section{实验设计}" + "\n")
    body.append(r"\subsection{实验流程}" + "\n")
    body.append(_itemize(plan.get("experiments") or (), ordered=True) + "\n")
    body.append(r"\subsection{基线对比（Baselines）}" + "\n")
    body.append(_itemize(plan.get("baselines") or ()) + "\n")
    body.append(r"\subsection{评估指标（Metrics）}" + "\n")
    body.append(_itemize(plan.get("metrics") or ()) + "\n")

    body.append(r"\section{实验结果}" + "\n")
    results = plan.get("results")
    if isinstance(results, str) and results.strip():
        body.append(_tex_escape(results) + "\n")
    else:
        # 计划阶段尚未执行是正常状态，但必须如实说明，不能留白让读者以为漏排。
        body.append(
            r"\textit{本计划尚未执行，故无实测结果。"
            r"预期结果与可反驳条件见下节。}" + "\n"
        )

    body.append(r"\section{预期结果与可反驳条件}" + "\n")
    body.append(_tex_escape(plan.get("expected_results")) + "\n")

    body.append(r"\section{风险与备选方案}" + "\n")
    body.append(_itemize(plan.get("risks_and_alternatives") or ()) + "\n")

    body.append(r"\section{参考论文}" + "\n")
    if references:
        body.append(
            r"\begin{enumerate}[label={[\arabic*]}]" + "\n"
            + "\n".join(rf"\item {_render_reference(r)}" for r in references)
            + "\n" + r"\end{enumerate}" + "\n"
        )
    else:
        body.append(
            r"\textbf{\textcolor{red}{参考文献缺失：榜题要求给出真实文献列表，"
            r"当前计划尚未接入文献检索。}}" + "\n"
        )
    if ref_problems and not strict_references:
        body.append(
            r"\vspace{0.4em}\noindent\textbf{\textcolor{red}{文献可核验性问题：}}"
            + "\n"
            + _itemize(ref_problems)
            + "\n"
        )

    body.append(r"\end{document}" + "\n")
    return "\n".join(body)
