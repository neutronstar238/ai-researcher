"""Deterministic technical-proposal builder for the contest mainline.

The contest requires a technical-proposal PDF of at most 20 pages covering the
problem and method, the multi-agent/Skills architecture, a real case study, and
a source-code inventory.  This module builds that document deterministically
from one completed mainline delivery: every number, hash, and file binding is
read from the delivery evidence, and no model is called.  A proposal that
renders to more than 20 pages fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from autoresearch.competition.contest_question_input import ContestQuestionInput
from autoresearch.research.plans import compile_research_plan_pdf

_DEFAULT_SOURCE = Path("runs/contest-delivery/mainline")
_DEFAULT_OUTPUT = Path("runs/contest-delivery/technical-proposal")
_DELIVERY_REPORT_NAME = "delivery-report.json"
_QUESTION_NAME = "question-input.json"
_METRICS_NAME = "metrics.json"
_PROPOSAL_SCHEMA = "contest-technical-proposal-v1"
_MAX_PAGES = 20
_REPO_ROOT = Path(__file__).resolve().parents[3]

# 技术方案引用的主线源码清单：模块、角色、主链/旁链标记。
_SOURCE_MODULES: tuple[tuple[str, str, str], ...] = (
    (
        "src/autoresearch/competition/contest_mainline_cli.py",
        "主线编排：题目→计划→真实预实验→反馈修订→最终 PDF",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_direct_plan_cli.py",
        "题目提取、Skill 目录发现与主链第一步编排",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_direct_skill_router.py",
        "题目后 Skill 元数据路由（只返回 Skill ID，不读正文）",
        "主线",
    ),
    (
        "src/autoresearch/competition/temporary_qwen_pool.py",
        "不记名临时子 Agent 并行池（归档后运行时身份消失）",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_research_objective_stage.py",
        "研究目标阶段：三角色探索 + 独立评审",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_direct_plan.py",
        "计划生成：通用 system 提示词 + 题目/交付契约",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_direct_plan_revision.py",
        "预实验反馈修订（一次模型调用 + 数字守卫）",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_direct_plan_render.py",
        "研究计划 JSON/Markdown/TeX/PDF 渲染与页数/文本核验",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_prime_preexperiment.py",
        "真实素数间隙预实验（排列熵 + 四零模型对照）",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_plan_embedded_evidence.py",
        "把预实验证据表图嵌入最终计划",
        "主线",
    ),
    (
        "src/autoresearch/competition/contest_reference_policy.py",
        "锁定文献目录投影与相关性排序（防虚构引用）",
        "主线",
    ),
    (
        "src/autoresearch/knowledge/raw_memory.py",
        "主权原始记忆（只追加、内容寻址）与 Dreaming 投影",
        "能力",
    ),
    (
        "src/autoresearch/competition/contest_direction_memory.py",
        "方向循环记忆桥：阶段产物镜像 + Dreaming 召回",
        "能力",
    ),
    (
        "src/autoresearch/competition/contest_direction_skill_evolution.py",
        "Skill 自进化：证据→草稿→留出集验证→激活/回滚",
        "能力",
    ),
    (
        "src/autoresearch/competition/contest_direction_research_loop_cli.py",
        "自主搜索灵感方向循环（十二阶段；标注：开发中）",
        "开发中",
    ),
    (
        "src/autoresearch/research/adaptive_sovereign_loop.py",
        "自适应科研双环：模型自选算子 + 晋级门（标注：开发中）",
        "开发中",
    ),
)

_ARCHITECTURE_SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "主 Agent（计划作者）",
        "通用 system 提示词只包含证据优先、可证伪主假设、对照与失败判据、复现路径等"
        "方法论；题目与交付要求作为 user 消息进入，科学正文由主 Agent 一次生成。",
    ),
    (
        "不记名临时子 Agent",
        "三个并行角色（可证伪假设探索、方法桥接与最小预实验、反方挑战）只返回中文"
        "内容 memo；程序生成全部 ID、哈希与状态，批次完成后运行时身份归档消失，"
        "内容与作者回执保留。主 Agent 可采纳、改写或全部拒绝其建议。",
    ),
    (
        "题目后 Skill 元数据路由",
        "专业方法论存放在 skills/*/SKILL.md，不进入通用 system 提示词。路由模型先"
        "只看到 name/description/content_sha256 元数据做选择，程序随后重读选中文件"
        "并验证正文 SHA-256，再以独立只读消息注入。",
    ),
    (
        "独立评审 Agent",
        "研究目标阶段结束时由独立能力评审候选假设并选择或综合研究目标，与作者身份"
        "分离，避免自评自写。",
    ),
    (
        "主权记忆与上下文压缩",
        "原始记忆（RawMemoryStore）只追加、内容寻址、逐条绑定字节哈希；Dreaming"
        "投影是可删除、可重建的派生导航，标注事实/解释/外推/矛盾/未知。上下文压缩"
        "发生在派生层，原始字节永不回写；Dreaming 不是科学证据。",
    ),
    (
        "Skill 自进化",
        "真实证据（论文与预实验）→ Skill 草稿 → 留出集案例评估 → 验证通过才激活，"
        "并保留回滚回执；旧 Skill 版本与原始证据不可变。",
    ),
    (
        "闭环主线 Loop",
        "题目 → 中文研究计划 → 真实预实验 → 反馈修订 → 最终 PDF 构成一条哈希绑定"
        "的闭环主线；每个阶段产物绑定上阶段哈希，失败关闭并保留失败证据。",
    ),
    (
        "文件与 URL 真实性核验",
        "文献引用只能选自锁定真实目录逐项编号；来源请求记录逐次物理 HTTP 回执"
        "（attempt ledger）；关键来源 URL 经过可达性状态核验后才进入计划。",
    ),
    (
        "标注：自主搜索灵感线（开发中）",
        "十二阶段方向研究循环（大方向检索 → 定向检索 → 覆盖门 → 假设 → 预实验 →"
        "评审）与自适应科研双环仍在开发迭代，不构成本次交付的依赖。",
    ),
)


class ContestTechnicalProposalError(RuntimeError):
    """Raised when the proposal cannot be built truthfully from delivery evidence."""


def build_technical_proposal_payload(
    source_delivery_dir: Path | str,
) -> dict[str, Any]:
    """Read one completed mainline delivery and assemble the proposal payload."""

    root = Path(source_delivery_dir).expanduser().resolve()
    if not root.is_dir():
        raise ContestTechnicalProposalError(
            f"mainline delivery directory is missing: {root}"
        )
    report = _read_json(root / _DELIVERY_REPORT_NAME)
    if report.get("schema_version") != "contest-mainline-delivery-v1":
        raise ContestTechnicalProposalError(
            "technical proposal requires a contest-mainline delivery"
        )
    if report.get("status") != "completed":
        raise ContestTechnicalProposalError("mainline delivery is not completed")
    question_path = Path(str(report["plan_stage"]["report"]["path"]))
    question_root = question_path.parent
    question = ContestQuestionInput.model_validate_json(
        (question_root / _QUESTION_NAME).read_text(encoding="utf-8")
    )

    pilot = report.get("preexperiment") or {}
    metrics_binding = pilot.get("metrics") or {}
    metrics_path = Path(str(metrics_binding["path"])).expanduser().resolve()
    if not metrics_path.is_file():
        raise ContestTechnicalProposalError(
            f"preexperiment metrics are missing: {metrics_path}"
        )
    _verify_binding(metrics_path, metrics_binding)
    metrics = _read_json(metrics_path)
    pilot_numbers = _pilot_aggregate_rows(metrics)

    revision = report.get("revision") or {}
    rendered = report.get("rendered") or {}
    pdf_binding = rendered.get("artifacts", {}).get("pdf") or {}
    final_pdf = Path(str(pdf_binding.get("path", ""))).expanduser().resolve()
    if not final_pdf.is_file():
        raise ContestTechnicalProposalError("final plan PDF is missing from delivery")
    _verify_binding(final_pdf, pdf_binding)

    inventory = [
        {
            "path": path,
            "role": role,
            "status": status,
            "sha256": _sha256_file(_REPO_ROOT / path),
            "size_bytes": (_REPO_ROOT / path).stat().st_size,
        }
        for path, role, status in _SOURCE_MODULES
        if (_REPO_ROOT / path).is_file()
    ]
    inventory_hash = _canonical_hash({"modules": inventory})
    delivery_report_binding = _binding(
        {"path": str(root / _DELIVERY_REPORT_NAME)}
    )

    return {
        "schema_version": _PROPOSAL_SCHEMA,
        "title": "面向「科学实验任务规划与反馈迭代」的多智能体自动科研系统技术方案",
        "question_zh": question.question_zh,
        "question_en": question.question_en,
        "mainline_flow": [
            "题目确定性提取（Science 125 第 1 题，绑定页码与 SHA-256）",
            "Skill 元数据路由（题目后按需选择专业方法技能）",
            "三个不记名临时子 Agent 并行探索 + 独立评审选定研究目标",
            "主 Agent 一次生成中文《科学假设与研究计划》",
            "真实素数间隙预实验（固定区间、四零模型对照、199 次重采样）",
            "主 Agent 读取已核验预实验结果修订计划一次（数字守卫内置）",
            "最终 JSON/Markdown/TeX/PDF 渲染与页数、文本核验",
        ],
        "architecture": [{"name": name, "detail": detail} for name, detail in _ARCHITECTURE_SECTIONS],
        "case_study": {
            "delivery_root": root.as_posix(),
            "delivery_report": delivery_report_binding,
            "plan_report_sha256": str(report["plan_stage"]["report"]["sha256"]),
            "pilot_run_id": str(pilot.get("run_id", "")),
            "pilot_status": str(pilot.get("status", "")),
            "pilot_numbers": pilot_numbers,
            "metrics_binding": metrics_binding,
            "revision_provider": str(revision.get("provider", "")),
            "revision_model_name": str(revision.get("model_name", "")),
            "final_plan_pdf": pdf_binding,
            "page_count": rendered.get("page_count"),
            "pdf_text_verified": rendered.get("pdf_text_verified"),
            "formal_experiment_executed": bool(report.get("formal_experiment_executed")),
            "paper_claimed": bool(report.get("paper_claimed")),
        },
        "source_inventory": inventory,
        "source_inventory_hash": inventory_hash,
    }


def render_technical_proposal_markdown(payload: Mapping[str, Any]) -> str:
    """Render the proposal payload as Markdown."""

    lines = [
        f"# {payload['title']}",
        "",
        "## 一、待研究问题与方法",
        "",
        f"题目：{payload['question_zh']}（{payload['question_en']}）",
        "",
        "主线闭环流程：",
        "",
        *[f"{index}. {step}" for index, step in enumerate(payload["mainline_flow"], start=1)],
        "",
        "## 二、多智能体 / Skills 架构",
        "",
        *[
            f"### {section['name']}\n\n{section['detail']}\n"
            for section in payload["architecture"]
        ],
        "## 三、真实案例",
        "",
        _markdown_case_study(payload["case_study"]),
        "",
        "## 四、源码说明",
        "",
        "| 文件 | 角色 | 状态 | 大小 | SHA-256 |",
        "|---|---|---|---|---|",
        *[
            f"| `{item['path']}` | {item['role']} | {item['status']} | "
            f"{item['size_bytes']} | `{item['sha256'][:16]}…` |"
            for item in payload["source_inventory"]
        ],
        "",
        f"源码清单哈希：`{payload['source_inventory_hash'][:16]}…`",
    ]
    return "\n".join(lines) + "\n"


def render_technical_proposal_tex(payload: Mapping[str, Any]) -> str:
    """Render the proposal payload as a UTF-8 ctexart LaTeX document."""

    case = payload["case_study"]
    pilot_rows = "\n".join(
        rf"{row[0]} & {row[1]} & {row[2]} & {row[3]} \\"
        for row in case["pilot_numbers"]
    )
    inventory_rows = "\n".join(
        rf"{_tex_escape(item['path'])} & {_tex_escape(item['role'])} & "
        rf"{_tex_escape(item['status'])} & {item['size_bytes']} & "
        rf"{item['sha256'][:16]}\ldots \\"
        for item in payload["source_inventory"]
    )
    architecture = "\n\n".join(
        rf"\subsection{{{_tex_escape(section['name'])}}}"
        + "\n"
        + f"{_tex_escape(section['detail'])}"
        for section in payload["architecture"]
    )
    flow = "\n".join(
        rf"\item {_tex_escape(step)}" for step in payload["mainline_flow"]
    )
    return rf"""\documentclass[UTF8,11pt,a4paper]{{ctexart}}
\usepackage[top=2.2cm,bottom=2.2cm,left=2.5cm,right=2.5cm]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{enumitem}}
\usepackage{{fancyhdr}}
\usepackage{{longtable}}
\usepackage[hidelinks]{{hyperref}}
\usepackage{{url}}
\usepackage{{xcolor}}

\definecolor{{planblue}}{{HTML}}{{155A8A}}
\hypersetup{{colorlinks=true,linkcolor=planblue,urlcolor=planblue}}
\ctexset{{
  section/format={{\heiti\zihao{{-3}}}},
  subsection/format={{\heiti\zihao{{4}}}}
}}
\linespread{{1.25}}
\setlength{{\parindent}}{{2em}}
\setlength{{\emergencystretch}}{{3em}}
\setlist[itemize]{{leftmargin=2em,itemsep=0.2em}}
\setlist[enumerate]{{leftmargin=2em,itemsep=0.2em}}
\pagestyle{{fancy}}
\fancyhf{{}}
\chead{{\songti 技术方案}}
\cfoot{{\thepage}}
\sloppy

\begin{{document}}
\begin{{center}}
{{\heiti\zihao{{2}} {_tex_escape(payload['title'])}}}\\[0.6em]
{{\songti\zihao{{4}} 科学实验任务规划与反馈迭代}}
\end{{center}}

\section{{待研究问题与方法}}
题目：{_tex_escape(payload['question_zh'])}（{_tex_escape(payload['question_en'])}）。

主线闭环流程：
\begin{{enumerate}}
{flow}
\end{{enumerate}}

\section{{多智能体 / Skills 架构}}
{architecture}

\section{{真实案例}}
案例来源（主线交付）：{_tex_escape(case['delivery_root'])}。

预实验：run\_id={_tex_escape(case['pilot_run_id'])}，状态={_tex_escape(case['pilot_status'])}；
修订模型：{_tex_escape(case['revision_provider'])} / {_tex_escape(case['revision_model_name'])}；
最终计划 PDF：{case['page_count']} 页，文本核验通过={case['pdf_text_verified']}。

预实验主指标（tie\_aware\_normalized\_permutation\_entropy\_m5，观察均值相对各零模型的
固定区间重采样差值，仅描述性）：
\begin{{longtable}}{{llll}}
\toprule
零模型 & 观察均值 & 零模型均值 & $\Delta$（观察$-$零模型） \\
\midrule
\endhead
{pilot_rows}
\bottomrule
\end{{longtable}}

交付边界：formal\_experiment\_executed={case['formal_experiment_executed']}，
paper\_claimed={case['paper_claimed']}；交付报告 SHA-256：
{_tex_escape(case['delivery_report']['sha256'])}。

\section{{源码说明}}
\begin{{longtable}}{{p{{0.42\linewidth}}p{{0.30\linewidth}}p{{0.10\linewidth}}rp{{0.10\linewidth}}}}
\toprule
文件 & 角色 & 状态 & 字节 & SHA-256（前 16 位） \\
\midrule
\endhead
{inventory_rows}
\bottomrule
\end{{longtable}}

源码清单哈希：{_tex_escape(payload['source_inventory_hash'])}。

\end{{document}}
"""


def materialize_technical_proposal(
    source_delivery_dir: Path | str,
    *,
    output_dir: Path | str,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Build, render, and verify the technical proposal; fail closed above 20 pages."""

    payload = build_technical_proposal_payload(source_delivery_dir)
    root = Path(output_dir).expanduser().resolve()
    _require_new_or_empty(root, create=True)
    json_path = root / "technical-proposal.json"
    markdown_path = root / "technical-proposal.md"
    tex_path = root / "technical-proposal.tex"
    _write_new_json(json_path, payload)
    markdown_path.write_text(
        render_technical_proposal_markdown(payload), encoding="utf-8", newline="\n"
    )
    tex_path.write_text(
        render_technical_proposal_tex(payload), encoding="utf-8", newline="\n"
    )
    status, pdf_path, reason, page_count = compile_research_plan_pdf(
        tex_path, timeout_seconds=timeout_seconds
    )
    if status != "compiled" or pdf_path is None or not pdf_path.is_file():
        log_path = tex_path.with_suffix(".compile.log")
        log_tail = (
            _tail(log_path.read_text(encoding="utf-8", errors="replace"))
            if log_path.exists()
            else ""
        )
        raise ContestTechnicalProposalError(
            f"technical proposal PDF compilation failed: {reason or status}；日志：{log_tail}"
        )
    if page_count is None or page_count < 1:
        raise ContestTechnicalProposalError(
            f"technical proposal page count is not a positive number: {page_count}"
        )
    if page_count > _MAX_PAGES:
        raise ContestTechnicalProposalError(
            f"technical proposal renders {page_count} pages, exceeding the "
            f"{_MAX_PAGES}-page contest limit"
        )
    report = {
        "schema_version": _PROPOSAL_SCHEMA,
        "status": "completed",
        "page_count": page_count,
        "page_limit": _MAX_PAGES,
        "page_limit_passed": page_count <= _MAX_PAGES,
        "artifacts": {
            "json": _binding({"path": str(json_path)}),
            "markdown": _binding({"path": str(markdown_path)}),
            "tex": _binding({"path": str(tex_path)}),
            "pdf": _binding({"path": str(pdf_path)}),
        },
        "source_inventory_hash": payload["source_inventory_hash"],
        "formal_experiment_executed": bool(
            payload["case_study"]["formal_experiment_executed"]
        ),
        "paper_claimed": bool(payload["case_study"]["paper_claimed"]),
    }
    report_path = root / "delivery-report.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    return returned


def _pilot_aggregate_rows(metrics: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for item in metrics.get("aggregate_results", ()):
        if not isinstance(item, Mapping):
            continue
        null_model = str(item.get("null_model", ""))
        if not null_model:
            continue
        rows.append(
            (
                _tex_escape(null_model),
                _fmt(item.get("observed_mean_entropy")),
                _fmt(item.get("null_mean_entropy")),
                _fmt(item.get("delta_observed_minus_null")),
            )
        )
    return rows


def _fmt(value: Any) -> str:
    if isinstance(value, int | float):
        return f"{value:.6f}"
    return _tex_escape(str(value))


def _markdown_case_study(case: Mapping[str, Any]) -> str:
    lines = [
        f"- 主线交付目录：`{case['delivery_root']}`",
        f"- 预实验 run_id：`{case['pilot_run_id']}`，状态：`{case['pilot_status']}`",
        f"- 修订模型：{case['revision_provider']} / {case['revision_model_name']}",
        f"- 最终计划 PDF：{case['page_count']} 页，文本核验通过：{case['pdf_text_verified']}",
        "",
        "预实验主指标（观察均值相对各零模型的固定区间重采样差值）：",
        "",
        "| 零模型 | 观察均值 | 零模型均值 | Δ（观察−零模型） |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |"
        for row in case["pilot_numbers"]
    )
    lines.append("")
    lines.append(
        f"- 交付边界：formal_experiment_executed={case['formal_experiment_executed']}，"
        f"paper_claimed={case['paper_claimed']}"
    )
    return "\n".join(lines)


def _binding(mapping: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(mapping["path"])).expanduser().resolve()
    if not path.is_file():
        raise ContestTechnicalProposalError(f"bound file does not exist: {path}")
    actual = _sha256_file(path)
    expected = mapping.get("sha256")
    if expected is not None and actual != expected:
        raise ContestTechnicalProposalError(f"bound file hash mismatch: {path}")
    return {"path": path.as_posix(), "sha256": actual, "size_bytes": path.stat().st_size}


def _verify_binding(path: Path, binding: Mapping[str, Any]) -> None:
    _binding({**binding, "path": str(path)})


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestTechnicalProposalError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContestTechnicalProposalError(f"JSON is not an object: {path}")
    return payload


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(content, encoding="utf-8", newline="\n")
    except FileExistsError as exc:
        raise ContestTechnicalProposalError(f"refusing to overwrite {path}") from exc


def _require_new_or_empty(path: Path, *, create: bool) -> None:
    if path.exists():
        if not path.is_dir():
            raise ContestTechnicalProposalError(f"output path is not a directory: {path}")
        if any(path.iterdir()):
            raise ContestTechnicalProposalError(
                f"output directory must be new or empty: {path}"
            )
    elif create:
        path.mkdir(parents=True, exist_ok=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _tex_escape(value: Any) -> str:
    text = str(value)
    for source, target in (
        ("\\", r"\textbackslash{}"),
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
        text = text.replace(source, target)
    return text


def _tail(text: str, *, limit: int = 1200) -> str:
    return text[-limit:] if len(text) > limit else text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从一次已完成的主线交付确定性生成 ≤20 页技术方案 PDF。"
    )
    parser.add_argument("--source-delivery-dir", type=Path, default=_DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = materialize_technical_proposal(
        args.source_delivery_dir,
        output_dir=args.output_dir,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through module smoke
    sys.exit(main())


__all__ = [
    "ContestTechnicalProposalError",
    "build_technical_proposal_payload",
    "main",
    "materialize_technical_proposal",
    "render_technical_proposal_markdown",
    "render_technical_proposal_tex",
]
