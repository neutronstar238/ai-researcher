"""Render a system-authored Chinese contest research plan without scientific gates.

This module is deliberately a presentation boundary.  It accepts the research
content that an upstream model produced, checks only that the fields required by
the contest template are present, and writes synchronized JSON, Markdown, TeX,
PDF, and manifest views.  It does not grade novelty, prose length, language
ratios, opportunity coverage, enum spellings, evidence quality, or scientific
merit.

The PDF compiler is the existing project compiler from
``autoresearch.research.plans``.  A missing or failed TeX toolchain is reported as
an error; a placeholder PDF is never created.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoresearch.kernel.contracts import canonical_json, canonical_sha256
from autoresearch.research.plans import compile_research_plan_pdf

_JSON_NAME = "research-plan.json"
_SOURCE_JSON_NAME = "research-plan-source.json"
_SOURCE_PRIVATE_DIR = "_private"
_MARKDOWN_NAME = "research-plan.md"
_TEX_NAME = "research-plan.tex"
_PDF_NAME = "research-plan.pdf"
_MANIFEST_NAME = "research-plan-manifest.json"
_MANIFEST_SCHEMA_VERSION = "contest-direct-plan-render-v3"
_REFERENCE_PROJECTION_VERSION = "bibliographic-display-v2"
_PRESENTATION_AUDIT_NAME = "presentation-render-audit.json"

_MACHINE_DISPLAY_LABELS = {
    "consecutive_integer_primes": "连续整数区间内按升序生成的素数序列（确定性筛法）",
    "ordered_consecutive_prime_gaps": "相邻连续素数之差形成的有序素数间隙序列",
    "prime-gap-information-theory-v1": "素数间隙信息论预实验流程",
    "global_permutation": "全局置换零模型",
    "local_block_permutation": "局部分块置换零模型",
    "residue_path_conditioned_permutation": "残基路径条件置换零模型",
    "wheel_210": "wheel-210 可除性约束零模型",
    "hardy_littlewood_ktuple_generative_null": ("Hardy–Littlewood k-tuple 生成式零模型"),
    "tie_aware_normalized_permutation_entropy_m5": ("含并列修正的五阶归一化排列熵（m=5）"),
    "fixed_interval_resampling_delta_ci95": "五个固定区间重采样差值范围",
    "standardized_effect": "模拟标准化诊断量",
}
_INTERNAL_TOKEN_LABELS = {
    "run_id": "运行批次",
    "adapter_id": "预实验流程",
    "artifact_hash": "证据完整性校验",
    "record_id": "文献记录",
    "revision_id": "计划版本",
    "input_hash": "输入完整性校验",
    "model_response_hash": "模型响应完整性校验",
    "metrics_sha256": "指标完整性校验",
    "manifest_sha256": "清单完整性校验",
    "record_sha256": "文献记录完整性校验",
}

_SUPERSCRIPT_RUN = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ]+")
_SUBSCRIPT_RUN = re.compile(r"[₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎]+")
_SUPERSCRIPT_TRANSLATION = str.maketrans(
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ",
    "0123456789+-=()n",
)
_SUBSCRIPT_TRANSLATION = str.maketrans(
    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎",
    "0123456789+-=()",
)

_REQUIRED_FIELDS: tuple[str, ...] = (
    "title",
    "abstract",
    "problem_statement",
    "rationale",
    "technical_details",
    "datasets",
    "methods",
    "experiments",
    "results",
    "references",
)


class ContestDirectPlanRenderError(RuntimeError):
    """Raised when required content is absent or a real PDF cannot be built."""


@dataclass(frozen=True)
class ContestDirectPlanArtifacts:
    """Stable paths and program-computed identities for one rendered plan."""

    output_dir: Path
    json_path: Path
    markdown_path: Path
    tex_path: Path
    pdf_path: Path
    manifest_path: Path
    source_payload_sha256: str
    page_count: int | None
    pdf_text_verified: bool
    source_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir.as_posix(),
            "json_path": self.json_path.as_posix(),
            "markdown_path": self.markdown_path.as_posix(),
            "tex_path": self.tex_path.as_posix(),
            "pdf_path": self.pdf_path.as_posix(),
            "manifest_path": self.manifest_path.as_posix(),
            "source_payload_sha256": self.source_payload_sha256,
            "page_count": self.page_count,
            "pdf_text_verified": self.pdf_text_verified,
            "source_path": self.source_path.as_posix() if self.source_path is not None else None,
        }


@dataclass(frozen=True)
class ContestDirectPlanPresentationArtifacts:
    """A versioned human-facing render linked to an immutable completed plan."""

    rendered: ContestDirectPlanArtifacts
    audit_path: Path
    audit_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rendered": self.rendered.to_dict(),
            "audit_path": self.audit_path.as_posix(),
            "audit_hash": self.audit_hash,
        }


@dataclass(frozen=True)
class _DisplayReference:
    """Human-facing bibliography projection of one evidence-bound reference.

    The upstream reference remains untouched in the private source sidecar.
    This value controls every public plan representation, including JSON.
    """

    citation: str
    url: str | None = None


def validate_contest_plan_payload(payload: Mapping[str, Any]) -> None:
    """Check only the fields necessary to render the contest template.

    Scientific and stylistic review intentionally belongs upstream.  In
    particular, this function has no minimum length, language ratio, enum,
    opportunity-grid, identifier, or hash requirements.
    """

    missing = [field for field in _REQUIRED_FIELDS if not _has_content(payload.get(field))]
    datasets = payload.get("datasets")
    if isinstance(datasets, Mapping):
        if not _has_content(datasets.get("source")):
            missing.append("datasets.source")
        if not _has_content(datasets.get("target")):
            missing.append("datasets.target")
    elif "datasets" not in missing:
        missing.extend(("datasets.source", "datasets.target"))

    experiments = payload.get("experiments")
    nested_experiments = experiments if isinstance(experiments, Mapping) else {}
    baselines = payload.get("baselines", nested_experiments.get("baselines"))
    metrics = payload.get("metrics", nested_experiments.get("metrics"))
    if not _has_content(baselines):
        missing.append("baselines")
    if not _has_content(metrics):
        missing.append("metrics")

    if missing:
        unique = list(dict.fromkeys(missing))
        raise ContestDirectPlanRenderError("研究计划缺少榜题模板必要字段：" + "、".join(unique))

    try:
        canonical_json(dict(payload))
    except (TypeError, ValueError) as exc:
        raise ContestDirectPlanRenderError(f"研究计划不是可保存的 JSON 数据：{exc}") from exc


def render_contest_plan_markdown(payload: Mapping[str, Any]) -> str:
    """Render a Chinese Markdown view without changing authored content."""

    validate_contest_plan_payload(payload)
    datasets = _mapping(payload["datasets"])
    baselines, metrics = _experiment_support(payload)
    embedded_evidence = _embedded_evidence(payload)
    lines = [
        f"# {_self_contained_prose(payload['title'])}",
        "",
        "## 摘要（Paper Abstract）",
        "",
        _markdown_value(payload["abstract"], humanize=True),
        "",
        "## 待研究问题（Problem Statement）",
        "",
        _markdown_value(payload["problem_statement"], humanize=True),
        "",
        "## 解决思路（Rationale）",
        "",
        _markdown_value(payload["rationale"], humanize=True),
        "",
        "## 必要的技术手段（Technical Details）",
        "",
        _markdown_value(payload["technical_details"], humanize=True),
        "",
        "## 数据集（Datasets）",
        "",
        "| 数据角色 | 本研究中的具体内容 |",
        "|---|---|",
        (
            "| 来源（Source） | "
            + _markdown_table_cell(_self_contained_prose(datasets["source"]))
            + " |"
        ),
        (
            "| 分析对象（Target） | "
            + _markdown_table_cell(_self_contained_prose(datasets["target"]))
            + " |"
        ),
        *(
            [
                "| 补充说明 | "
                + _markdown_table_cell(_self_contained_prose(datasets["description"]))
                + " |"
            ]
            if _has_content(datasets.get("description"))
            else []
        ),
        "",
        "## 方法论（Methods）",
        "",
        _markdown_value(payload["methods"], humanize=True),
        "",
        "## 实验设计（Experiments）",
        "",
        _markdown_value(_experiment_steps(payload["experiments"]), ordered=True, humanize=True),
        "",
        "### 基线对比（Baselines）",
        "",
        _markdown_value(_display_items(baselines), humanize=True),
        "",
        "### 评估指标（Metrics）",
        "",
        _markdown_value(_display_items(metrics), humanize=True),
        "",
        "## 实验结果（Results）",
        "",
        _markdown_value(payload["results"], humanize=True),
        "",
    ]
    if embedded_evidence is not None:
        lines.extend(
            ("## 预实验数据、图表与分析", "", _markdown_embedded_evidence(embedded_evidence), "")
        )
    lines.extend(
        (
            "## 参考论文（References）",
            "",
            _markdown_references(payload["references"]),
            "",
        )
    )
    return "\n".join(lines)


def render_contest_plan_tex(payload: Mapping[str, Any]) -> str:
    """Render a UTF-8 ``ctexart`` document from the supplied plan."""

    validate_contest_plan_payload(payload)
    datasets = _mapping(payload["datasets"])
    baselines, metrics = _experiment_support(payload)
    embedded_evidence = _embedded_evidence(payload)
    experiments = _tex_items(
        _as_items(_experiment_steps(payload["experiments"])),
        ordered=True,
        humanize=True,
    )
    baseline_items = _tex_items(_display_items(baselines), humanize=True)
    metric_items = _tex_items(_display_items(metrics), humanize=True)
    reference_items = "\n".join(
        rf"\item {_tex_reference(reference)}" for reference in _as_items(payload["references"])
    )

    return rf"""\documentclass[UTF8,12pt,a4paper]{{ctexart}}
\usepackage[top=2.5cm,bottom=2.5cm,left=2.7cm,right=2.7cm]{{geometry}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage{{booktabs}}
\usepackage{{enumitem}}
\usepackage{{fancyhdr}}
\usepackage{{float}}
\usepackage{{graphicx}}
\usepackage[hidelinks]{{hyperref}}
\usepackage{{pgfplots}}
\usepackage{{tabularx}}
\usepackage{{url}}
\usepackage{{xcolor}}

\definecolor{{planblue}}{{HTML}}{{155A8A}}
\hypersetup{{colorlinks=true,linkcolor=planblue,urlcolor=planblue}}
\pgfplotsset{{compat=1.18}}
\ctexset{{
  section/format={{\heiti\zihao{{-3}}}},
  subsection/format={{\heiti\zihao{{4}}}}
}}
\linespread{{1.35}}
\setlength{{\parindent}}{{2em}}
\setlength{{\emergencystretch}}{{3em}}
\setlist[itemize]{{leftmargin=2em,itemsep=0.25em}}
\setlist[enumerate]{{leftmargin=2em,itemsep=0.25em}}
\pagestyle{{fancy}}
\fancyhf{{}}
\chead{{\songti 科学假设与研究计划}}
\cfoot{{\thepage}}
\sloppy

\begin{{document}}
\begin{{center}}
{{\heiti\zihao{{2}} {_tex_escape(_self_contained_prose(payload['title']))}}}\\[0.8em]
{{\songti\zihao{{4}} 科学假设与研究计划}}
\end{{center}}

\section*{{摘要（Paper Abstract）}}
{_tex_paragraphs(payload['abstract'], humanize=True)}

\section{{待研究问题（Problem Statement）}}
{_tex_paragraphs(payload['problem_statement'], humanize=True)}

\section{{解决思路（Rationale）}}
{_tex_paragraphs(payload['rationale'], humanize=True)}

\section{{必要的技术手段（Technical Details）}}
{_tex_paragraphs(payload['technical_details'], humanize=True)}

\section{{数据集（Datasets）}}
\begin{{tabularx}}{{\linewidth}}{{@{{}}lX@{{}}}}
\toprule
\textbf{{来源（Source）}} & {_tex_escape(_self_contained_prose(datasets['source']))} \\
\midrule
\textbf{{分析对象（Target）}} & {_tex_escape(_self_contained_prose(datasets['target']))} \\
{_tex_dataset_description_row(datasets)}
\bottomrule
\end{{tabularx}}

\section{{方法论（Methods）}}
{_tex_paragraphs(payload['methods'], humanize=True)}

\section{{实验设计（Experiments）}}
{experiments}

\subsection{{基线对比（Baselines）}}
{baseline_items}

\subsection{{评估指标（Metrics）}}
{metric_items}

\section{{实验结果（Results）}}
{_tex_paragraphs(payload['results'], humanize=True)}

{_tex_embedded_evidence_section(embedded_evidence)}

\section{{参考论文（References）}}
\begin{{enumerate}}[label={{[\arabic*]}}]
{reference_items}
\end{{enumerate}}

\end{{document}}
"""


def materialize_contest_direct_plan(
    *,
    payload: Mapping[str, Any],
    output_dir: Path | str,
    evidence_bindings: Sequence[Mapping[str, Any]] = (),
    overwrite: bool = False,
    timeout_seconds: int = 120,
) -> ContestDirectPlanArtifacts:
    """Write synchronized plan views and compile a real, text-readable PDF.

    Existing valid artifacts for the same source payload are returned unchanged.
    Different stable artifacts are protected by default; callers may explicitly
    pass ``overwrite=True`` when replacing them is intended.
    """

    validate_contest_plan_payload(payload)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    _pop_render_repairs()  # discard any repairs recorded by a previous render call
    source_hash = canonical_sha256(dict(payload))
    normalized_evidence_bindings = _normalize_evidence_bindings(evidence_bindings)
    evidence_bindings_hash = canonical_sha256({"evidence_bindings": normalized_evidence_bindings})
    existing = _load_idempotent_artifacts(
        output,
        source_hash,
        evidence_bindings_hash=(evidence_bindings_hash if normalized_evidence_bindings else None),
    )
    if existing is not None:
        return existing

    stable_paths = _stable_paths(output)
    source_path = output / _SOURCE_PRIVATE_DIR / _SOURCE_JSON_NAME
    conflicts = [path for path in (*stable_paths.values(), source_path) if path.exists()]
    if conflicts and not overwrite:
        names = "、".join(path.name for path in conflicts)
        raise ContestDirectPlanRenderError(
            f"输出目录已有不同或不完整的稳定制品（{names}）；"
            "如确认替换，请显式传入 overwrite=True"
        )

    source_bytes = (
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    public_payload = _public_plan_projection(payload)
    json_bytes = (
        json.dumps(public_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    markdown_bytes = render_contest_plan_markdown(public_payload).encode("utf-8")
    tex_bytes = render_contest_plan_tex(public_payload).encode("utf-8")
    latex_repairs = _pop_render_repairs()

    with tempfile.TemporaryDirectory(prefix=".research-plan-build-", dir=output) as temp_name:
        staging = Path(temp_name)
        staged_json = staging / _JSON_NAME
        staged_source = staging / _SOURCE_JSON_NAME
        staged_markdown = staging / _MARKDOWN_NAME
        staged_tex = staging / _TEX_NAME
        staged_json.write_bytes(json_bytes)
        staged_source.write_bytes(source_bytes)
        staged_markdown.write_bytes(markdown_bytes)
        staged_tex.write_bytes(tex_bytes)

        status, staged_pdf, reason, page_count = compile_research_plan_pdf(
            staged_tex,
            timeout_seconds=timeout_seconds,
        )
        if status != "compiled" or staged_pdf is None or not staged_pdf.is_file():
            log_path = staged_tex.with_suffix(".compile.log")
            log_tail = (
                _tail(log_path.read_text(encoding="utf-8", errors="replace"))
                if log_path.exists()
                else ""
            )
            detail = f"；编译日志末尾：{log_tail}" if log_tail else ""
            raise ContestDirectPlanRenderError(
                f"无法生成真实研究计划 PDF：{reason or status}{detail}"
            )
        if staged_pdf.stat().st_size == 0:
            raise ContestDirectPlanRenderError("LaTeX 编译返回了空 PDF，未发布任何制品")

        extracted_text = _extract_pdf_text(staged_pdf, timeout_seconds=timeout_seconds)
        _verify_pdf_text(extracted_text, title=_display_text(payload["title"]))

        staged_files = {
            "json": staged_json,
            "source": staged_source,
            "markdown": staged_markdown,
            "tex": staged_tex,
            "pdf": staged_pdf,
        }
        display_references = [
            _reference_plain_text(reference) for reference in _as_items(payload["references"])
        ]
        manifest = {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "source_payload_sha256": source_hash,
            "public_payload_sha256": canonical_sha256(public_payload),
            "reference_projection_version": _REFERENCE_PROJECTION_VERSION,
            "display_references": display_references,
            "display_references_sha256": canonical_sha256(
                {"display_references": display_references}
            ),
            "embedded_evidence": {
                "present": _embedded_evidence(payload) is not None,
                "content_sha256": (
                    canonical_sha256(dict(_embedded_evidence(payload) or {}))
                    if _embedded_evidence(payload) is not None
                    else None
                ),
                "table_count": _embedded_evidence_count(payload, "tables"),
                "figure_count": _embedded_evidence_count(payload, "figures"),
                "provenance_bindings": normalized_evidence_bindings,
                "provenance_bindings_sha256": evidence_bindings_hash,
            },
            "compile_status": "compiled",
            "compiler": _compiler_identity(),
            "latex_repairs": list(latex_repairs),
            "page_count": page_count,
            "pdf_text_verified": True,
            "artifacts": {
                kind: {
                    "filename": (
                        f"{_SOURCE_PRIVATE_DIR}/{_SOURCE_JSON_NAME}"
                        if kind == "source"
                        else path.name
                    ),
                    "sha256": _sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for kind, path in staged_files.items()
            },
        }
        staged_manifest = staging / _MANIFEST_NAME
        staged_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        publish_order = (
            (staged_json, stable_paths["json"]),
            (staged_source, source_path),
            (staged_markdown, stable_paths["markdown"]),
            (staged_tex, stable_paths["tex"]),
            (staged_pdf, stable_paths["pdf"]),
            (staged_manifest, stable_paths["manifest"]),
        )
        for source, target in publish_order:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)

    return ContestDirectPlanArtifacts(
        output_dir=output,
        json_path=stable_paths["json"],
        markdown_path=stable_paths["markdown"],
        tex_path=stable_paths["tex"],
        pdf_path=stable_paths["pdf"],
        manifest_path=stable_paths["manifest"],
        source_payload_sha256=source_hash,
        page_count=page_count,
        pdf_text_verified=True,
        source_path=source_path,
    )


def materialize_versioned_contest_plan_presentation(
    *,
    source_dir: Path | str,
    output_dir: Path | str,
    completion_bindings: Mapping[str, Path | str] | None = None,
    timeout_seconds: int = 120,
) -> ContestDirectPlanPresentationArtifacts:
    """Render a polished sibling without mutating a completed standard plan.

    The source JSON remains the scientific source of truth.  This function
    verifies the completed source render, writes an independent presentation,
    and binds both sets of bytes plus optional outer completion receipts in a
    content-hashed audit.  It never calls a model or changes scientific content.
    """

    source = Path(source_dir).resolve()
    output = Path(output_dir).resolve()
    if source == output:
        raise ContestDirectPlanRenderError("版本化展示目录不得与已完成标准计划目录相同")
    source_paths = _stable_paths(source)
    missing = [path.name for path in source_paths.values() if not path.is_file()]
    if missing:
        raise ContestDirectPlanRenderError("已完成标准计划缺少稳定制品：" + "、".join(missing))
    source_manifest = _read_json_mapping(source_paths["manifest"])
    source_records = source_manifest.get("artifacts")
    source_sidecar = source / _SOURCE_PRIVATE_DIR / _SOURCE_JSON_NAME
    if (
        isinstance(source_records, Mapping)
        and isinstance(source_records.get("source"), Mapping)
        and source_sidecar.is_file()
    ):
        source_record = source_records["source"]
        if source_record.get(
            "filename"
        ) != f"{_SOURCE_PRIVATE_DIR}/{_SOURCE_JSON_NAME}" or source_record.get(
            "sha256"
        ) != _sha256_file(source_sidecar):
            raise ContestDirectPlanRenderError("标准计划 internal source binding 校验失败")
        source_payload = _read_json_mapping(source_sidecar)
    else:
        # Legacy v2 renders stored the complete source in research-plan.json.
        source_payload = _read_json_mapping(source_paths["json"])
    source_hash = canonical_sha256(dict(source_payload))
    if source_manifest.get("source_payload_sha256") != source_hash:
        raise ContestDirectPlanRenderError("标准计划 manifest 与 JSON source hash 不一致")
    records = source_manifest.get("artifacts")
    if not isinstance(records, Mapping):
        raise ContestDirectPlanRenderError("标准计划 manifest 缺少 artifact inventory")
    for kind in ("json", "markdown", "tex", "pdf"):
        record = records.get(kind)
        if not isinstance(record, Mapping):
            raise ContestDirectPlanRenderError(f"标准计划 manifest 缺少 {kind} binding")
        path = source_paths[kind]
        if record.get("filename") != path.name or record.get("sha256") != _sha256_file(path):
            raise ContestDirectPlanRenderError(f"标准计划 {kind} binding 校验失败")

    source_embedded = source_manifest.get("embedded_evidence")
    source_evidence_bindings = (
        source_embedded.get("provenance_bindings", ())
        if isinstance(source_embedded, Mapping)
        else ()
    )
    rendered = materialize_contest_direct_plan(
        payload=source_payload,
        output_dir=output,
        evidence_bindings=(
            source_evidence_bindings
            if isinstance(source_evidence_bindings, Sequence)
            and not isinstance(source_evidence_bindings, str | bytes)
            else ()
        ),
        overwrite=False,
        timeout_seconds=timeout_seconds,
    )
    source_artifacts = {path.name: _file_binding(path) for path in source_paths.values()}
    if source_sidecar.is_file():
        source_artifacts[source_sidecar.name] = _file_binding(source_sidecar)
    presentation_paths = _stable_paths(output)
    presentation_artifacts = {
        path.name: _file_binding(path) for path in presentation_paths.values()
    }
    if rendered.source_path is not None:
        presentation_artifacts[rendered.source_path.name] = _file_binding(rendered.source_path)
    bound_completions: dict[str, dict[str, Any]] = {}
    for name, raw_path in sorted((completion_bindings or {}).items()):
        label = str(name).strip()
        path = Path(raw_path).resolve()
        if not label or not path.is_file():
            raise ContestDirectPlanRenderError(
                "presentation completion binding 必须使用非空名称和现有文件"
            )
        bound_completions[label] = _file_binding(path)
    audit: dict[str, Any] = {
        "schema_version": "contest-plan-presentation-audit-v1",
        "purpose": "human_readable_bibliography_projection_only",
        "source_standard_dir": source.as_posix(),
        "source_standard_artifacts": source_artifacts,
        "source_completion_bindings": bound_completions,
        "presentation_dir": output.as_posix(),
        "presentation_artifacts": presentation_artifacts,
        "reference_projection_version": _REFERENCE_PROJECTION_VERSION,
        "source_json_byte_identical": (
            source_paths["json"].read_bytes() == presentation_paths["json"].read_bytes()
        ),
        "scientific_content_changed": False,
        "model_calls": 0,
        "retrieval_calls": 0,
        "preexperiment_calls": 0,
        "formal_experiment_calls": 0,
    }
    audit_hash = canonical_sha256(audit)
    audit["audit_hash"] = audit_hash
    audit_path = output / _PRESENTATION_AUDIT_NAME
    _write_immutable_json(audit_path, audit)
    return ContestDirectPlanPresentationArtifacts(
        rendered=rendered,
        audit_path=audit_path,
        audit_hash=audit_hash,
    )


def _load_idempotent_artifacts(
    output_dir: Path,
    source_hash: str,
    *,
    evidence_bindings_hash: str | None,
) -> ContestDirectPlanArtifacts | None:
    paths = _stable_paths(output_dir)
    manifest_path = paths["manifest"]
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != _MANIFEST_SCHEMA_VERSION
        or manifest.get("reference_projection_version") != _REFERENCE_PROJECTION_VERSION
        or manifest.get("source_payload_sha256") != source_hash
    ):
        return None
    if evidence_bindings_hash is not None:
        embedded = manifest.get("embedded_evidence")
        if (
            not isinstance(embedded, Mapping)
            or embedded.get("provenance_bindings_sha256") != evidence_bindings_hash
        ):
            return None
    records = manifest.get("artifacts")
    if not isinstance(records, dict):
        return None
    for kind in ("json", "markdown", "tex", "pdf"):
        record = records.get(kind)
        path = paths[kind]
        if not isinstance(record, dict) or not path.is_file():
            return None
        if record.get("filename") != path.name or record.get("sha256") != _sha256_file(path):
            return None
    source_record = records.get("source")
    source_path = output_dir / _SOURCE_PRIVATE_DIR / _SOURCE_JSON_NAME
    if not isinstance(source_record, Mapping) or not source_path.is_file():
        return None
    if source_record.get(
        "filename"
    ) != f"{_SOURCE_PRIVATE_DIR}/{_SOURCE_JSON_NAME}" or source_record.get(
        "sha256"
    ) != _sha256_file(source_path):
        return None
    try:
        source_payload = _read_json_mapping(source_path)
    except ContestDirectPlanRenderError:
        return None
    if canonical_sha256(source_payload) != source_hash:
        return None
    page_count = manifest.get("page_count")
    if not isinstance(page_count, int):
        page_count = None
    return ContestDirectPlanArtifacts(
        output_dir=output_dir,
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        tex_path=paths["tex"],
        pdf_path=paths["pdf"],
        manifest_path=manifest_path,
        source_payload_sha256=source_hash,
        page_count=page_count,
        pdf_text_verified=manifest.get("pdf_text_verified") is True,
        source_path=source_path,
    )


def _extract_pdf_text(pdf_path: Path, *, timeout_seconds: int) -> str:
    extractor = shutil.which("pdftotext")
    if extractor is None:
        raise ContestDirectPlanRenderError(
            "PDF 已编译但系统缺少 pdftotext，无法验证其文字可读取；未发布任何制品"
        )
    try:
        completed = subprocess.run(
            (extractor, "-layout", str(pdf_path), "-"),
            cwd=pdf_path.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ContestDirectPlanRenderError("PDF 文字提取超时，未发布任何制品") from exc
    if completed.returncode != 0 or not completed.stdout.strip():
        detail = _tail(completed.stderr)
        raise ContestDirectPlanRenderError(
            f"PDF 无法提取文字，未发布任何制品：{detail or completed.returncode}"
        )
    return completed.stdout


def _verify_pdf_text(text: str, *, title: str) -> None:
    compact = re.sub(r"\s+", "", text)
    missing = [
        marker
        for marker in (title, "待研究问题", "实验结果", "参考论文")
        if re.sub(r"\s+", "", marker) not in compact
    ]
    if missing:
        raise ContestDirectPlanRenderError(
            "PDF 已生成但文字视图缺少必要章节：" + "、".join(missing)
        )


def _stable_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "json": output_dir / _JSON_NAME,
        "markdown": output_dir / _MARKDOWN_NAME,
        "tex": output_dir / _TEX_NAME,
        "pdf": output_dir / _PDF_NAME,
        "manifest": output_dir / _MANIFEST_NAME,
    }


def _experiment_support(payload: Mapping[str, Any]) -> tuple[Any, Any]:
    experiments = payload.get("experiments")
    nested = experiments if isinstance(experiments, Mapping) else {}
    return (
        payload.get("baselines", nested.get("baselines")),
        payload.get("metrics", nested.get("metrics")),
    )


def _experiment_steps(experiments: Any) -> Any:
    if not isinstance(experiments, Mapping):
        return experiments
    for key in ("steps", "procedure", "design"):
        if _has_content(experiments.get(key)):
            return experiments[key]
    return [
        {key: value} for key, value in experiments.items() if key not in {"baselines", "metrics"}
    ]


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContestDirectPlanRenderError("datasets 必须包含 source 与 target")
    return value


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping | Sequence):
        return bool(value)
    return True


def _as_items(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        return list(value)
    return [value]


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _display_text(value: Any) -> str:
    """Translate implementation identifiers only at the human-facing boundary."""

    text = _text(value)
    for machine, label in sorted(
        _MACHINE_DISPLAY_LABELS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        text = text.replace(machine, label)
    return text


def _display_items(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        return list(value)
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[；;\n]+", value) if part.strip()]
        return parts or [value]
    return [value]


def _public_plan_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project the internal payload to a self-contained public plan JSON.

    Upstream model receipts, run IDs, hashes, local paths, retrieval records and
    full abstracts remain in ``research-plan-source.json`` and the render
    manifest.  The public JSON contains the same scientific prose plus embedded
    evidence values and clean bibliography only.
    """

    datasets = _mapping(payload["datasets"])
    baselines, metrics = _experiment_support(payload)
    experiments = payload.get("experiments")
    projected: dict[str, Any] = {
        "document_type": _display_text(payload.get("document_type", "科学假设与研究计划")),
        "title": _self_contained_prose(payload["title"]),
        "abstract": _self_contained_prose(payload["abstract"]),
        "problem_statement": _self_contained_prose(payload["problem_statement"]),
        "rationale": _self_contained_prose(payload["rationale"]),
        "technical_details": _self_contained_prose(payload["technical_details"]),
        "datasets": {
            "description": _self_contained_prose(datasets.get("description", "")),
            "source": _self_contained_prose(datasets["source"]),
            "target": _self_contained_prose(datasets["target"]),
        },
        "methods": _self_contained_prose(payload["methods"]),
        "experiments": {
            "steps": _public_humanize(_experiment_steps(experiments)),
            "baselines": "；".join(
                _self_contained_prose(item) for item in _display_items(baselines)
            ),
            "metrics": "；".join(_self_contained_prose(item) for item in _display_items(metrics)),
        },
        "results": _self_contained_prose(payload["results"]),
        "references": [
            (
                projected_reference.citation
                + (
                    f"；URL：{projected_reference.url}"
                    if projected_reference.url is not None
                    else ""
                )
            )
            for reference in _as_items(payload["references"])
            for projected_reference in (_project_reference_for_display(reference),)
        ],
    }
    specified_direction = payload.get("specified_direction")
    if _has_content(specified_direction):
        projected["specified_direction"] = _self_contained_prose(specified_direction)
    evidence = _embedded_evidence(payload)
    if evidence is not None:
        projected["embedded_evidence"] = _public_evidence_projection(evidence)
        projected["preexperiment_summary"] = {
            "executed": True,
            "study_phase_zh": _display_text(evidence.get("execution_label_zh", "探索性预实验")),
            "formal_experiment_executed": False,
            "mathematical_proof_claimed": False,
        }
    else:
        preexperiment = payload.get("preexperiment")
        if isinstance(preexperiment, Mapping):
            executed = bool(preexperiment.get("executed", False))
            projected["preexperiment_summary"] = {
                "executed": executed,
                "study_phase_zh": "预实验" if executed else "尚未执行预实验",
                "formal_experiment_executed": False,
                "mathematical_proof_claimed": False,
            }
    return projected


def _public_evidence_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Expose scientific values without leaking internal table field names.

    The private source keeps the exact program keys used to bind metrics.  The
    public JSON instead uses the already-authored Chinese column labels as row
    keys, so it remains readable and self-contained while Markdown/TeX/PDF can
    render the same values without knowing implementation identifiers.
    """

    projected = _public_humanize(dict(evidence))
    if not isinstance(projected, dict):  # pragma: no cover - mapping input invariant
        raise ContestDirectPlanRenderError("公开预实验证据投影失败")
    raw_tables = evidence.get("tables")
    public_tables = projected.get("tables")
    if (
        isinstance(raw_tables, Sequence)
        and not isinstance(raw_tables, str | bytes)
        and isinstance(public_tables, list)
    ):
        for raw_table, public_table in zip(raw_tables, public_tables, strict=False):
            if not isinstance(raw_table, Mapping) or not isinstance(public_table, dict):
                continue
            public_table.pop("table_id", None)
            raw_columns = raw_table.get("columns")
            raw_rows = raw_table.get("rows")
            if (
                not isinstance(raw_columns, Sequence)
                or isinstance(raw_columns, str | bytes)
                or not isinstance(raw_rows, Sequence)
                or isinstance(raw_rows, str | bytes)
            ):
                continue
            key_pairs: list[tuple[str, str]] = []
            used: set[str] = set()
            for ordinal, column in enumerate(raw_columns, start=1):
                if not isinstance(column, Mapping):
                    continue
                source_key = str(column.get("key") or "").strip()
                label = _display_text(column.get("label_zh") or f"列{ordinal}")
                if not source_key or not label:
                    continue
                public_key = label
                suffix = 2
                while public_key in used:
                    public_key = f"{label}（{suffix}）"
                    suffix += 1
                used.add(public_key)
                key_pairs.append((source_key, public_key))
            public_table["columns"] = [
                {"key": public_key, "label_zh": public_key} for _source_key, public_key in key_pairs
            ]
            public_table["rows"] = [
                {
                    public_key: _public_humanize(row.get(source_key))
                    for source_key, public_key in key_pairs
                }
                for row in raw_rows
                if isinstance(row, Mapping)
            ]
    figures = projected.get("figures")
    if isinstance(figures, list):
        for figure in figures:
            if isinstance(figure, dict):
                figure.pop("figure_id", None)
    return projected


def _public_humanize(value: Any) -> Any:
    if isinstance(value, str):
        return _self_contained_prose(value)
    if isinstance(value, Mapping):
        preserved_string_fields = {
            "schema_version",
            "table_id",
            "figure_id",
            "kind",
            "key",
        }
        return {
            str(key): (
                item
                if str(key) in preserved_string_fields and isinstance(item, str)
                else _public_humanize(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_public_humanize(item) for item in value]
    return value


def _self_contained_prose(value: Any) -> str:
    text = _display_text(value)
    for token, label in sorted(
        _INTERNAL_TOKEN_LABELS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        text = re.sub(
            rf"(?i)\b{re.escape(token)}\b\s*[:=]\s*[A-Za-z0-9._:/-]+",
            label,
            text,
        )
        text = re.sub(rf"(?i)\b{re.escape(token)}\b", label, text)
    # Local artifact paths and sidecar filenames are implementation provenance,
    # not research prose.  The complete bytes remain in the private source and
    # manifest; the public plan directly embeds their reportable contents.
    # Stripping happens before LaTeX normalization so Windows paths (C:\...) can
    # never be mistaken for unresolved commands by the render gate.
    text = re.sub(
        r"(?i)(?:(?<![A-Za-z])[A-Za-z]:[/\\][^\s，。；]+|(?:[\w.-]+[/\\])+[\w.-]+\.(?:jsonl?|csv|tsv|log|txt))",
        "本计划内嵌证据",
        text,
    )
    text = re.sub(
        r"(?i)(?<![\w.-])[\w.-]+\.(?:jsonl?|csv|tsv|log)(?![\w.-])",
        "本计划内嵌证据",
        text,
    )
    return _normalize_latex_math_in_text(text)


def _markdown_table_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", "<br>")


def _embedded_evidence(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = payload.get("embedded_evidence")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ContestDirectPlanRenderError("embedded_evidence 必须是结构化对象")
    if value.get("schema_version") != "contest-plan-embedded-evidence-v1":
        raise ContestDirectPlanRenderError("embedded_evidence schema_version 不受支持")
    tables = value.get("tables")
    figures = value.get("figures")
    if not isinstance(tables, Sequence) or isinstance(tables, str | bytes):
        raise ContestDirectPlanRenderError("embedded_evidence.tables 必须是数组")
    if not isinstance(figures, Sequence) or isinstance(figures, str | bytes):
        raise ContestDirectPlanRenderError("embedded_evidence.figures 必须是数组")
    return value


def _embedded_evidence_count(payload: Mapping[str, Any], key: str) -> int:
    evidence = _embedded_evidence(payload)
    if evidence is None:
        return 0
    value = evidence.get(key)
    return len(value) if isinstance(value, Sequence) else 0


def _markdown_embedded_evidence(evidence: Mapping[str, Any]) -> str:
    lines = [
        _display_text(evidence.get("summary_zh", "")),
        "",
    ]
    tables = evidence.get("tables", ())
    for ordinal, table in enumerate(tables, start=1):
        if not isinstance(table, Mapping):
            continue
        lines.extend(_markdown_evidence_table(table, ordinal=ordinal))
    figures = evidence.get("figures", ())
    for ordinal, figure in enumerate(figures, start=1):
        if not isinstance(figure, Mapping):
            continue
        lines.extend(_markdown_evidence_figure(figure, ordinal=ordinal))
    analysis = _display_text(evidence.get("analysis_zh", ""))
    if analysis:
        lines.extend(("### 综合分析", "", analysis, ""))
    scope = _display_text(evidence.get("scope_note_zh", ""))
    if scope:
        lines.extend(("> **解释边界：** " + scope, ""))
    return "\n".join(lines).rstrip()


def _markdown_evidence_table(table: Mapping[str, Any], *, ordinal: int) -> list[str]:
    title = _display_text(table.get("title_zh", f"预实验数据表 {ordinal}"))
    columns = _table_columns(table)
    rows = _table_rows(table)
    if not columns or not rows:
        return []
    labels = [label for _key, label in columns]
    lines = [
        f"### 表 {ordinal}　{title}",
        "",
        "| " + " | ".join(_markdown_table_cell(label) for label in labels) + " |",
        "|" + "|".join("---" for _ in labels) + "|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _markdown_table_cell(_format_display_value(row.get(key))) for key, _label in columns
            )
            + " |"
        )
    caption = _display_text(table.get("caption_zh", ""))
    analysis = _display_text(table.get("analysis_zh", ""))
    lines.extend(("", f"*表注：{caption}*" if caption else "", ""))
    if analysis:
        lines.extend((f"**表格分析：** {analysis}", ""))
    return [line for line in lines if line or line == ""]


def _markdown_evidence_figure(figure: Mapping[str, Any], *, ordinal: int) -> list[str]:
    title = _display_text(figure.get("title_zh", f"预实验图 {ordinal}"))
    svg = _inline_interval_svg(figure)
    if not svg:
        return []
    caption = _display_text(figure.get("caption_zh", ""))
    analysis = _display_text(figure.get("analysis_zh", ""))
    lines = [f"### 图 {ordinal}　{title}", "", svg, ""]
    if caption:
        lines.extend((f"*图注：{caption}*", ""))
    if analysis:
        lines.extend((f"**图形分析：** {analysis}", ""))
    return lines


def _inline_interval_svg(figure: Mapping[str, Any]) -> str:
    series = _figure_series(figure)
    if not series:
        return ""
    width = 820
    left = 250
    right = 45
    top = 36
    row_height = 48
    bottom = 58
    height = top + len(series) * row_height + bottom
    values = [value for _label, value, lower, upper in series for value in (lower, value, upper)]
    minimum = min(values + [0.0])
    maximum = max(values + [0.0])
    span = maximum - minimum
    padding = span * 0.08 if span else max(abs(maximum), 1.0) * 0.08
    xmin = minimum - padding
    xmax = maximum + padding
    plot_width = width - left - right

    def x(value: float) -> float:
        return left + (value - xmin) / (xmax - xmin) * plot_width

    zero_x = x(0.0)
    fragments = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-label="{html.escape(_display_text(figure.get("title_zh", "预实验差值图")))}" '
            f'viewBox="0 0 {width} {height}" width="100%">'
        ),
        "<style>text{font-family:Arial,'Microsoft YaHei',sans-serif;fill:#222}"
        ".label{font-size:14px}.value{font-size:13px}.axis{font-size:13px}</style>",
        f'<line x1="{zero_x:.2f}" y1="20" x2="{zero_x:.2f}" y2="{height-bottom+8}" '
        'stroke="#777" stroke-width="1.2" stroke-dasharray="5 4"/>',
    ]
    for index, (label, value, lower, upper) in enumerate(series):
        y = top + index * row_height + row_height / 2
        fragments.extend(
            (
                f'<text class="label" x="{left-12}" y="{y+5:.2f}" text-anchor="end">'
                f"{html.escape(_display_text(label))}</text>",
                f'<line x1="{x(lower):.2f}" y1="{y:.2f}" x2="{x(upper):.2f}" '
                'y2="{y:.2f}" stroke="#0072B2" stroke-width="3"/>'.format(y=y),
                f'<line x1="{x(lower):.2f}" y1="{y-6:.2f}" x2="{x(lower):.2f}" '
                f'y2="{y+6:.2f}" stroke="#0072B2" stroke-width="2"/>',
                f'<line x1="{x(upper):.2f}" y1="{y-6:.2f}" x2="{x(upper):.2f}" '
                f'y2="{y+6:.2f}" stroke="#0072B2" stroke-width="2"/>',
                f'<circle cx="{x(value):.2f}" cy="{y:.2f}" r="5" fill="#D55E00" '
                'stroke="#111" stroke-width="1"/>',
                f'<text class="value" x="{min(x(value)+9, width-right-60):.2f}" '
                f'y="{y+5:.2f}">{html.escape(_format_display_number(value))}</text>',
            )
        )
    fragments.extend(
        (
            f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" '
            f'y2="{height-bottom}" stroke="#222"/>',
            f'<text class="axis" x="{(left+width-right)/2:.2f}" y="{height-16}" '
            f'text-anchor="middle">{html.escape(_display_text(figure.get("x_label_zh", "差值")))}</text>',
            "</svg>",
        )
    )
    return "".join(fragments)


def _tex_dataset_description_row(datasets: Mapping[str, Any]) -> str:
    if not _has_content(datasets.get("description")):
        return ""
    return (
        r"\midrule"
        + "\n"
        + r"\textbf{补充说明} & "
        + _tex_escape(_self_contained_prose(datasets["description"]))
        + r" \\"
        + "\n"
    )


def _tex_embedded_evidence_section(evidence: Mapping[str, Any] | None) -> str:
    if evidence is None:
        return ""
    blocks = [
        r"\section{预实验数据、图表与分析}",
        _tex_paragraphs(evidence.get("summary_zh", ""), humanize=True),
    ]
    tables = evidence.get("tables", ())
    for ordinal, table in enumerate(tables, start=1):
        if isinstance(table, Mapping):
            rendered = _tex_evidence_table(table, ordinal=ordinal)
            if rendered:
                blocks.append(rendered)
    figures = evidence.get("figures", ())
    for ordinal, figure in enumerate(figures, start=1):
        if isinstance(figure, Mapping):
            rendered = _tex_evidence_figure(figure, ordinal=ordinal)
            if rendered:
                blocks.append(rendered)
    analysis = _display_text(evidence.get("analysis_zh", ""))
    if analysis:
        blocks.extend((r"\subsection*{综合分析}", _tex_paragraphs(analysis)))
    scope = _display_text(evidence.get("scope_note_zh", ""))
    if scope:
        blocks.append(
            r"\noindent\colorbox{planblue!8}{\parbox{0.95\linewidth}{\textbf{解释边界：}"
            + _tex_escape(scope)
            + "}}"
        )
    return "\n\n".join(blocks)


def _tex_evidence_table(table: Mapping[str, Any], *, ordinal: int) -> str:
    columns = _table_columns(table)
    rows = _table_rows(table)
    if not columns or not rows:
        return ""
    title = _display_text(table.get("title_zh", f"预实验数据表 {ordinal}"))
    column_spec = "l" * len(columns)
    header = " & ".join(r"\textbf{" + _tex_escape(label) + "}" for _key, label in columns)
    row_lines = [
        " & ".join(_tex_escape(_format_display_value(row.get(key))) for key, _label in columns)
        + r" \\"
        for row in rows
    ]
    caption = _display_text(table.get("caption_zh", ""))
    analysis = _display_text(table.get("analysis_zh", ""))
    return "\n".join(
        (
            r"\begin{table}[H]",
            r"\centering",
            r"\small",
            r"\resizebox{\linewidth}{!}{%",
            rf"\begin{{tabular}}{{@{{}}{column_spec}@{{}}}}",
            r"\toprule",
            header + r" \\",
            r"\midrule",
            *row_lines,
            r"\bottomrule",
            r"\end{tabular}%",
            "}",
            rf"\caption{{{_tex_escape(title)}。{_tex_escape(caption)}}}",
            r"\end{table}",
            r"\noindent\textbf{表格分析：} " + _tex_escape(analysis) if analysis else "",
        )
    )


def _tex_evidence_figure(figure: Mapping[str, Any], *, ordinal: int) -> str:
    series = _figure_series(figure)
    if not series:
        return ""
    ticks = ",".join(str(index) for index in range(1, len(series) + 1))
    labels = ",".join(
        "{" + _tex_escape(_display_text(label)) + "}" for label, _value, _lower, _upper in series
    )
    coordinates = " ".join(
        f"({_format_tex_number(value)},{index})"
        for index, (_label, value, _lower, _upper) in enumerate(series, start=1)
    )
    interval_lines = "\n".join(
        (
            rf"\draw[planblue,line width=1.1pt] "
            rf"(axis cs:{_format_tex_number(lower)},{index}) -- "
            rf"(axis cs:{_format_tex_number(upper)},{index});"
        )
        for index, (_label, _value, lower, upper) in enumerate(series, start=1)
    )
    values = [number for _label, value, lower, upper in series for number in (lower, value, upper)]
    minimum = min(values + [0.0])
    maximum = max(values + [0.0])
    span = maximum - minimum
    padding = span * 0.1 if span else max(abs(maximum), 1.0) * 0.1
    midpoint = (minimum + maximum) / 2
    value_labels = "\n".join(
        (
            rf"\node[anchor={'west' if value <= midpoint else 'east'},"
            rf"xshift={'2pt' if value <= midpoint else '-2pt'},"
            rf"font=\scriptsize,text=black] at "
            rf"(axis cs:{_format_tex_number(value)},{index}) "
            rf"{{{_tex_escape(_format_display_number(value))}}};"
        )
        for index, (_label, value, _lower, _upper) in enumerate(series, start=1)
    )
    title = _display_text(figure.get("title_zh", f"预实验图 {ordinal}"))
    x_label = _display_text(figure.get("x_label_zh", "差值"))
    caption = _display_text(figure.get("caption_zh", ""))
    analysis = _display_text(figure.get("analysis_zh", ""))
    return "\n".join(
        (
            r"\begin{figure}[H]",
            r"\centering",
            r"\begin{tikzpicture}",
            r"\begin{axis}[",
            r"  width=0.62\linewidth,",
            rf"  height={max(5.2, 1.05 * len(series) + 2.2):.2f}cm,",
            rf"  xmin={_format_tex_number(minimum-padding)},",
            rf"  xmax={_format_tex_number(maximum+padding)},",
            rf"  ytick={{{ticks}}},",
            rf"  yticklabels={{{labels}}},",
            r"  y dir=reverse,",
            r"  axis y line*=left,",
            r"  y axis line style={draw=none},",
            r"  ytick style={draw=none},",
            r"  axis x line*=bottom,",
            rf"  xlabel={{{_tex_escape(x_label)}}},",
            r"  tick label style={font=\small},",
            r"  yticklabel style={font=\small,text width=4.2cm,align=right},",
            r"  label style={font=\small},",
            r"  grid=major,",
            r"  xmajorgrids=true,",
            r"  ymajorgrids=false,",
            r"]",
            interval_lines,
            r"\addplot+[only marks,mark=*,mark size=2.4pt,color=planblue] coordinates {",
            coordinates,
            r"};",
            value_labels,
            r"\draw[dashed,gray] (axis cs:0,0.5) -- (axis cs:0," + f"{len(series)+0.5}" + r");",
            r"\end{axis}",
            r"\end{tikzpicture}",
            rf"\caption{{{_tex_escape(title)}。{_tex_escape(caption)}}}",
            r"\end{figure}",
            r"\noindent\textbf{图形分析：} " + _tex_escape(analysis) if analysis else "",
        )
    )


def _table_columns(table: Mapping[str, Any]) -> list[tuple[str, str]]:
    value = table.get("columns")
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    columns: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        key = item.get("key")
        label = item.get("label_zh")
        if isinstance(key, str) and key.strip() and isinstance(label, str) and label.strip():
            columns.append((key, _display_text(label)))
    return columns


def _table_rows(table: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = table.get("rows")
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _figure_series(figure: Mapping[str, Any]) -> list[tuple[str, float, float, float]]:
    value = figure.get("series")
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    series: list[tuple[str, float, float, float]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        label = item.get("label")
        point = _float_or_none(item.get("value"))
        lower = _float_or_none(item.get("lower", point))
        upper = _float_or_none(item.get("upper", point))
        if (
            isinstance(label, str)
            and point is not None
            and lower is not None
            and upper is not None
            and lower <= point <= upper
        ):
            series.append((label, point, lower, upper))
    return series


def _format_display_value(value: Any) -> str:
    if isinstance(value, str):
        return _display_text(value)
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return _format_display_number(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes) and len(value) == 2:
        return "[" + ", ".join(_format_display_value(item) for item in value) + "]"
    return "—" if value is None else _display_text(value)


def _format_display_number(value: float) -> str:
    absolute = abs(value)
    if absolute != 0 and (absolute < 0.0001 or absolute >= 1_000_000):
        return f"{value:.3e}"
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _format_tex_number(value: float) -> str:
    return f"{value:.12g}"


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _normalize_evidence_bindings(
    bindings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw in bindings:
        if not isinstance(raw, Mapping):
            raise ContestDirectPlanRenderError("evidence binding 必须是对象")
        role = str(raw.get("role", "")).strip()
        path_value = raw.get("path")
        sha256 = raw.get("sha256")
        size_bytes = raw.get("size_bytes")
        if not role or not isinstance(path_value, str) or not path_value.strip():
            raise ContestDirectPlanRenderError("evidence binding 缺少 role 或 path")
        path = Path(path_value).resolve()
        if not path.is_file():
            raise ContestDirectPlanRenderError(f"evidence binding 文件不存在：{path}")
        actual_hash = _sha256_file(path)
        if not isinstance(sha256, str) or sha256 != actual_hash:
            raise ContestDirectPlanRenderError(f"evidence binding SHA-256 不匹配：{path.name}")
        if not isinstance(size_bytes, int) or size_bytes != path.stat().st_size:
            raise ContestDirectPlanRenderError(f"evidence binding 大小不匹配：{path.name}")
        normalized_path = path.as_posix()
        if normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        normalized.append(
            {
                "role": role,
                "path": normalized_path,
                "sha256": actual_hash,
                "size_bytes": size_bytes,
            }
        )
    return sorted(normalized, key=lambda item: (item["path"], item["role"]))


def _markdown_value(
    value: Any,
    *,
    ordered: bool = False,
    humanize: bool = False,
) -> str:
    if isinstance(value, list | tuple):
        prefix = (lambda index: f"{index}. ") if ordered else (lambda _index: "- ")
        return "\n".join(
            f"{prefix(index)}{_normalize_latex_math_in_text(_self_contained_prose(item) if humanize else _text(item))}"
            for index, item in enumerate(value, 1)
        )
    if isinstance(value, Mapping):
        return "\n".join(
            f"- **{key}：** {_normalize_latex_math_in_text(_self_contained_prose(item) if humanize else _text(item))}"
            for key, item in value.items()
        )
    return _normalize_latex_math_in_text(_self_contained_prose(value) if humanize else _text(value))


def _markdown_references(value: Any) -> str:
    return "\n".join(
        f"{index}. {_reference_plain_text(reference)}"
        for index, reference in enumerate(_as_items(value), 1)
    )


def _reference_plain_text(reference: Any) -> str:
    projected = _project_reference_for_display(reference)
    citation = _normalize_latex_math_in_text(projected.citation)
    if projected.url is None:
        return citation
    return f"{citation}；URL：{projected.url}"


def _tex_items(
    items: Sequence[Any],
    *,
    ordered: bool = False,
    humanize: bool = False,
) -> str:
    environment = "enumerate" if ordered else "itemize"
    body = "\n".join(
        rf"\item {_tex_escape(_self_contained_prose(item) if humanize else item)}" for item in items
    )
    return f"\\begin{{{environment}}}\n{body}\n\\end{{{environment}}}"


def _tex_paragraphs(value: Any, *, humanize: bool = False) -> str:
    text = _self_contained_prose(value) if humanize else _text(value)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return "\n\n\\par\n".join(_tex_escape(part) for part in paragraphs)


def _tex_reference(reference: Any) -> str:
    projected = _project_reference_for_display(reference)
    if projected.url is None:
        return _tex_escape(projected.citation)
    return (
        _tex_escape(projected.citation) + r"；URL：" + rf"\url{{{_tex_url_escape(projected.url)}}}"
    )


def _project_reference_for_display(reference: Any) -> _DisplayReference:
    """Remove transport/audit fields while retaining verifiable bibliography.

    Real retrieval catalogs intentionally contain abstracts, retrieval lineage,
    hashes and metric provenance.  Those fields remain byte-for-byte in the JSON
    source artifact, but they are not bibliography and must not be printed into a
    human-facing report.
    """

    if isinstance(reference, str) and "；URL：" in reference:
        citation, url = reference.rsplit("；URL：", 1)
        if url.startswith(("http://", "https://")):
            return _self_contained_reference(citation=citation, url=url)
    if isinstance(reference, Mapping) and _clean_reference_value(reference.get("citation")):
        citation = _clean_reference_value(reference.get("citation"))
        mapped_url = _clean_reference_value(reference.get("url")) or None
        return _self_contained_reference(citation=citation, url=mapped_url)
    if isinstance(reference, Mapping):
        fields = _reference_fields_from_mapping(reference)
    elif isinstance(reference, str):
        fields = _reference_fields_from_catalog_text(reference)
    else:
        fields = {}
    if not fields.get("title"):
        text = _text(reference)
        if text.startswith(("http://", "https://")):
            return _DisplayReference(citation="在线资料", url=text)
        return _self_contained_reference(
            citation=_normalize_unicode_math_display(text),
            url=None,
        )

    parts: list[str] = []
    if fields.get("authors"):
        parts.append(f"作者：{fields['authors']}")
    parts.append(f"题名：{_normalize_unicode_math_display(fields['title'])}")
    if fields.get("year"):
        parts.append(f"年份：{fields['year']}")
    if fields.get("venue"):
        parts.append(f"期刊/会议：{fields['venue']}")
    if fields.get("doi"):
        parts.append(f"正式 DOI：{fields['doi']}")
    elif fields.get("repository_doi"):
        parts.append(f"仓储 DOI：{fields['repository_doi']}")
    if fields.get("source"):
        parts.append(f"元数据来源：{fields['source']}")
    return _self_contained_reference(
        citation="；".join(parts),
        url=fields.get("url"),
    )


def _self_contained_reference(*, citation: str, url: str | None) -> _DisplayReference:
    """Remove local retrieval provenance while retaining public source URLs."""

    cleaned = re.sub(
        r"(?i)\s*local\s+source\s+sha-?256\s*:\s*[0-9a-f]{64}\s*[;；]?\s*",
        " ",
        citation,
    )
    cleaned = re.sub(
        r"(?i)\s*source\s*:\s*[A-Za-z]:[/\\][^;；\r\n]*[;；]?\s*",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\b[0-9a-f]{64}\b", "", cleaned)
    # Unstructured legacy references often put their canonical web URL at the
    # end of the citation instead of in a dedicated field.  Promote only the
    # final public URL; earlier URLs (for example a two-entry OEIS citation)
    # remain readable citation text.
    if not url:
        matches = list(re.finditer(r"https?://[^\s；;]+", cleaned))
        if matches:
            match = matches[-1]
            url = match.group(0).rstrip(".,)")
            cleaned = cleaned[: match.start()] + cleaned[match.end() :]
    cleaned = _self_contained_prose(cleaned)
    cleaned = re.sub(r"\s*[;；]+\s*", "；", cleaned).strip(" ；;,.，")
    safe_url = (url or "").strip()
    if safe_url and not safe_url.startswith(("http://", "https://")):
        safe_url = ""
    return _DisplayReference(citation=cleaned or "在线资料", url=safe_url or None)


def _reference_fields_from_mapping(reference: Mapping[str, Any]) -> dict[str, str]:
    authors = reference.get("authors", reference.get("author"))
    if isinstance(authors, list | tuple):
        author_text = "、".join(_clean_reference_value(author) for author in authors)
    else:
        author_text = _clean_reference_value(authors)
    date = _first_reference_value(
        reference,
        "year",
        "publication_year",
        "publication_date",
        "date",
    )
    return _clean_reference_fields(
        {
            "authors": author_text,
            "title": _first_reference_value(reference, "title", "paper_title"),
            "year": _reference_year(date),
            "venue": _first_reference_value(
                reference,
                "venue",
                "journal",
                "conference",
                "container_title",
            ),
            "doi": _first_reference_value(reference, "doi", "publication_doi"),
            "repository_doi": _first_reference_value(reference, "repository_doi"),
            "url": _first_reference_value(reference, "url", "source_url"),
            "source": _first_reference_value(reference, "paper_source", "source"),
        }
    )


def _reference_fields_from_catalog_text(reference: str) -> dict[str, str]:
    aliases = {
        "题名": "title",
        "作者": "authors",
        "日期": "date",
        "年份": "date",
        "期刊或会议": "venue",
        "DOI": "doi",
        "正式发表DOI": "doi",
        "仓储DOI": "repository_doi",
        "URL": "url",
        "论文来源字段": "source",
    }
    fields: dict[str, str] = {}
    for line in reference.splitlines():
        match = re.match(r"^\s*([^：=]+?)\s*[：=]\s*(.*?)\s*$", line)
        if match is None:
            continue
        key = aliases.get(match.group(1).strip())
        if key is not None and key not in fields:
            fields[key] = match.group(2)
    if "title" not in fields:
        return {}
    fields["year"] = _reference_year(fields.pop("date", ""))
    return _clean_reference_fields(fields)


def _clean_reference_fields(fields: Mapping[str, str]) -> dict[str, str]:
    cleaned = {
        key: _clean_reference_value(value)
        for key, value in fields.items()
        if _clean_reference_value(value)
    }
    for key in ("doi", "repository_doi"):
        value = cleaned.get(key)
        if value:
            cleaned[key] = re.sub(
                r"^https?://(?:dx\.)?doi\.org/",
                "",
                value,
                flags=re.IGNORECASE,
            )
    url = cleaned.get("url")
    if url and not url.startswith(("http://", "https://")):
        cleaned.pop("url", None)
    return cleaned


def _clean_reference_value(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", _text(value)).strip()
    if text in {
        "未提供",
        "作者信息未提供",
        "日期未提供",
        "未知",
        "null",
        "None",
    }:
        return ""
    return text


def _first_reference_value(reference: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean_reference_value(reference.get(key))
        if value:
            return value
    return ""


def _reference_year(value: str) -> str:
    match = re.search(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})(?!\d)", value)
    return match.group(1) if match is not None else ""


def _normalize_unicode_math_display(value: str) -> str:
    """Project fragile Unicode math glyphs to portable bibliography text."""

    normalized = value.replace("⋅", "×").replace("∙", "×")
    normalized = _SUPERSCRIPT_RUN.sub(
        lambda match: "^" + match.group(0).translate(_SUPERSCRIPT_TRANSLATION),
        normalized,
    )
    return _SUBSCRIPT_RUN.sub(
        lambda match: "_" + match.group(0).translate(_SUBSCRIPT_TRANSLATION),
        normalized,
    )


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestDirectPlanRenderError(f"无法读取 JSON 制品：{path}") from exc
    if not isinstance(payload, dict):
        raise ContestDirectPlanRenderError(f"JSON 制品顶层必须是对象：{path}")
    return payload


def _file_binding(path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().as_posix(),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != encoded:
            raise ContestDirectPlanRenderError(f"版本化展示审计已存在且内容不同：{path}") from None


# Model-authored prose frequently carries raw LaTeX math notation (``$...$``,
# ``\{...\}``, ``\in``, ``^{...}``, ``_{...}``).  Escaping those tokens verbatim
# leaks ``\$`` / ``\textbackslash{}`` / ``\{`` into the human-facing document
# instead of typesetting them.  This table maps the bounded command set the plan
# model actually emits onto Unicode symbols that the escape path below renders
# through ``\ensuremath{}`` (so they survive a font without CJK/math glyphs).
_LATEX_MATH_COMMANDS: dict[str, str] = {
    r"\in": "∈",
    r"\notin": "∉",
    r"\leq": "≤",
    r"\le": "≤",
    r"\geq": "≥",
    r"\ge": "≥",
    r"\neq": "≠",
    r"\ne": "≠",
    r"\times": "×",
    r"\cdot": "·",
    r"\pm": "±",
    r"\mp": "∓",
    r"\approx": "≈",
    r"\simeq": "≃",
    r"\sim": "∼",
    r"\propto": "∝",
    r"\to": "→",
    r"\rightarrow": "→",
    r"\leftarrow": "←",
    r"\leftrightarrow": "↔",
    r"\Rightarrow": "⇒",
    r"\infty": "∞",
    r"\sum": "∑",
    r"\prod": "∏",
    r"\int": "∫",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\forall": "∀",
    r"\exists": "∃",
    r"\subset": "⊂",
    r"\subseteq": "⊆",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\land": "∧",
    r"\wedge": "∧",
    r"\lor": "∨",
    r"\vee": "∨",
    r"\neg": "¬",
    r"\ldots": "…",
    r"\dots": "…",
    r"\cdots": "⋯",
    r"\mid": "|",
    r"\ln": "ln",
    r"\log": "log",
    r"\exp": "exp",
    r"\sin": "sin",
    r"\cos": "cos",
    r"\tan": "tan",
    r"\cot": "cot",
    r"\sec": "sec",
    r"\csc": "csc",
    r"\min": "min",
    r"\max": "max",
    r"\det": "det",
    r"\lim": "lim",
    r"\sup": "sup",
    r"\inf": "inf",
    r"\dim": "dim",
    r"\deg": "deg",
    r"\gg": "≫",
    r"\ll": "≪",
    r"\gtrsim": "≳",
    r"\lesssim": "≲",
    r"\star": "⋆",
    r"\ast": "∗",
    r"\Re": "ℜ",
    r"\Im": "ℑ",
    r"\hbar": "ħ",
    r"\ell": "ℓ",
    r"\langle": "⟨",
    r"\rangle": "⟩",
    r"\prime": "′",
    r"\dagger": "†",
    r"\angle": "∠",
    r"\circ": "∘",
    r"\Vert": "‖",
    r"\vert": "|",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\varepsilon": "ε",
    r"\zeta": "ζ",
    r"\eta": "η",
    r"\theta": "θ",
    r"\iota": "ι",
    r"\kappa": "κ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\nu": "ν",
    r"\xi": "ξ",
    r"\pi": "π",
    r"\rho": "ρ",
    r"\sigma": "σ",
    r"\tau": "τ",
    r"\upsilon": "υ",
    r"\phi": "φ",
    r"\varphi": "φ",
    r"\chi": "χ",
    r"\psi": "ψ",
    r"\omega": "ω",
    r"\Gamma": "Γ",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Xi": "Ξ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Phi": "Φ",
    r"\Psi": "Ψ",
    r"\Omega": "Ω",
}

# Unicode math symbols produced by the normalization pass (or already present in
# model text) that the CJK body font may lack; render them through math mode.
_MATH_SYMBOLS: dict[str, str] = {
    "≤": r"\ensuremath{\leq}",
    "≥": r"\ensuremath{\geq}",
    "≠": r"\ensuremath{\neq}",
    "∈": r"\ensuremath{\in}",
    "∉": r"\ensuremath{\notin}",
    "×": r"\ensuremath{\times}",
    "·": r"\ensuremath{\cdot}",
    "±": r"\ensuremath{\pm}",
    "∓": r"\ensuremath{\mp}",
    "≈": r"\ensuremath{\approx}",
    "≃": r"\ensuremath{\simeq}",
    "∼": r"\ensuremath{\sim}",
    "∝": r"\ensuremath{\propto}",
    "→": r"\ensuremath{\rightarrow}",
    "←": r"\ensuremath{\leftarrow}",
    "↔": r"\ensuremath{\leftrightarrow}",
    "⇒": r"\ensuremath{\Rightarrow}",
    "∞": r"\ensuremath{\infty}",
    "∑": r"\ensuremath{\sum}",
    "∏": r"\ensuremath{\prod}",
    "∫": r"\ensuremath{\int}",
    "√": r"\ensuremath{\surd}",
    "∂": r"\ensuremath{\partial}",
    "∇": r"\ensuremath{\nabla}",
    "∀": r"\ensuremath{\forall}",
    "∃": r"\ensuremath{\exists}",
    "⊂": r"\ensuremath{\subset}",
    "⊆": r"\ensuremath{\subseteq}",
    "∪": r"\ensuremath{\cup}",
    "∩": r"\ensuremath{\cap}",
    "∧": r"\ensuremath{\land}",
    "∨": r"\ensuremath{\lor}",
    "¬": r"\ensuremath{\neg}",
    "≳": r"\ensuremath{\gtrsim}",
    "≲": r"\ensuremath{\lesssim}",
    "−": r"\ensuremath{-}",
    "α": r"\ensuremath{\alpha}",
    "β": r"\ensuremath{\beta}",
    "γ": r"\ensuremath{\gamma}",
    "δ": r"\ensuremath{\delta}",
    "ε": r"\ensuremath{\varepsilon}",
    "ζ": r"\ensuremath{\zeta}",
    "η": r"\ensuremath{\eta}",
    "θ": r"\ensuremath{\theta}",
    "ι": r"\ensuremath{\iota}",
    "κ": r"\ensuremath{\kappa}",
    "λ": r"\ensuremath{\lambda}",
    "μ": r"\ensuremath{\mu}",
    "ν": r"\ensuremath{\nu}",
    "ξ": r"\ensuremath{\xi}",
    "π": r"\ensuremath{\pi}",
    "ρ": r"\ensuremath{\rho}",
    "σ": r"\ensuremath{\sigma}",
    "τ": r"\ensuremath{\tau}",
    "υ": r"\ensuremath{\upsilon}",
    "φ": r"\ensuremath{\varphi}",
    "χ": r"\ensuremath{\chi}",
    "ψ": r"\ensuremath{\psi}",
    "ω": r"\ensuremath{\omega}",
    "Γ": r"\ensuremath{\Gamma}",
    "Δ": r"\ensuremath{\Delta}",
    "Θ": r"\ensuremath{\Theta}",
    "Λ": r"\ensuremath{\Lambda}",
    "Ξ": r"\ensuremath{\Xi}",
    "Π": r"\ensuremath{\Pi}",
    "Σ": r"\ensuremath{\Sigma}",
    "Φ": r"\ensuremath{\Phi}",
    "Ψ": r"\ensuremath{\Psi}",
    "Ω": r"\ensuremath{\Omega}",
}

_COMMANDS_SORTED_BY_LENGTH = tuple(
    sorted(_LATEX_MATH_COMMANDS, key=len, reverse=True)
)

# Unknown commands remaining after every known projection: braced commands take
# their inner text, bare commands keep the command word without the backslash.
_UNKNOWN_COMMAND_RE = re.compile(r"\\(?P<command>[A-Za-z]+)(?:\s*\{(?P<inner>[^{}]*)\})?")


class _RenderRepairLedger(threading.local):
    """Per-thread ledger of automatic LaTeX repairs performed by one render."""

    def __init__(self) -> None:
        self.repairs: list[str] = []


_render_repair_ledger = _RenderRepairLedger()


def _pop_render_repairs() -> tuple[str, ...]:
    """Return and clear the repairs recorded by the current render call."""

    ledger = _render_repair_ledger.repairs
    repairs = tuple(ledger)
    ledger.clear()
    return repairs


def _normalize_latex_math_in_text(text: str) -> str:
    r"""Project model-authored LaTeX math notation onto plain Unicode text.

    This is a display-only normalization.  It never changes scientific content;
    it only removes LaTeX math delimiters and command syntax so the document body
    reads as clean text instead of leaking ``$``, ``\{``, or ``\in``.  The
    resulting Unicode symbols are then routed through math mode by ``_tex_escape``
    so they survive a CJK font that lacks Greek/math glyphs.
    """

    normalized = text.replace("$$", "").replace(r"\[", "").replace(r"\]", "")
    normalized = normalized.replace(r"\(", "").replace(r"\)", "").replace("$", "")
    # Repair the plan model's JSON-escaping corruption: a bare backslash command
    # (``\t`` / ``\tau``) inside a JSON string value is folded by the JSON parser
    # into a tab / tab+"au" before this renderer ever runs.  Plan prose never uses
    # tabs, so these two replacements restore the intended math text.
    normalized = normalized.replace("\t" + "au", "τ")
    # Restore other LaTeX commands whose leading ``\t`` was folded into a tab by
    # the JSON parser before this renderer runs.  The restored commands flow
    # through the regular projections below (``\text{...}``/``\tilde{...}``
    # collapse to their inner text, ``\times`` maps to ×, ``\theta`` maps to θ).
    normalized = normalized.replace("\t" + "ext", r"\text")
    normalized = normalized.replace("\t" + "ilde", r"\tilde")
    normalized = normalized.replace("\t" + "imes", r"\times")
    normalized = normalized.replace("\t" + "heta", r"\theta")
    normalized = normalized.replace(r"\tfrac", r"\frac")
    normalized = normalized.replace("\t", "t")
    # Repair the same JSON-escaping corruption for ``\b`` (backspace escape):
    # ``\bar`` / ``\beta`` / ``\binom`` become a raw backspace byte plus the
    # remaining letters.  Restoring the ``\b`` prefix lets the command projections
    # below process them normally (``\bar{...}`` collapses to its inner text,
    # ``\beta`` maps to β); an unmatched stray backspace is dropped.
    normalized = re.sub(r"\x08([A-Za-z]+)", r"\\b\1", normalized)
    normalized = normalized.replace("\x08", "")
    # Brace-grouped typographic/accent commands collapse to their inner text.
    normalized = re.sub(
        r"\\(?:text|mathrm|mathbf|mathit|mathsf|mathtt|textbf|textit|operatorname"
        r"|bar|hat|vec|tilde|overline|underline|widehat|widetilde|dot|ddot|mathring"
        r"|mathcal|mathbb|mathfrak|mathscr|bm|boldsymbol)"
        r"\s*\{([^{}]*)\}",
        r"\1",
        normalized,
    )
    normalized = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1/\2", normalized)
    normalized = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", normalized)
    normalized = normalized.replace(r"\{", "{").replace(r"\}", "}")
    normalized = re.sub(r"\^\{([^{}]*)\}", r"^\1", normalized)
    normalized = re.sub(r"_\{([^{}]*)\}", r"_\1", normalized)
    # Known single-token commands map to their Unicode/math text equivalents.
    # Matching requires a non-letter after the command so that a shorter known
    # command can never eat the prefix of a longer unknown one (e.g. ``\pm``
    # must not corrupt ``\pmatrix`` into ``±atrix``).
    command_pattern = re.compile(
        r"\\" + r"(?:"
        + "|".join(re.escape(command[1:]) for command in _COMMANDS_SORTED_BY_LENGTH)
        + r")(?![A-Za-z])"
    )
    normalized = command_pattern.sub(
        lambda match: _LATEX_MATH_COMMANDS[match.group(0)], normalized
    )
    # A model-written literal ``\n`` (escaped backslash inside its JSON output)
    # survives parsing as backslash+n; it means a line break, not a command.
    normalized = normalized.replace(r"\n", " ")
    # A redundant backslash directly before an already-Unicode math/greek symbol
    # (e.g. ``\κ`` written instead of ``\kappa``) is dropped.
    normalized = re.sub(r"\\(?=[\u0370-\u03ff\u2200-\u22ff])", "", normalized)
    for command in (r"\,", r"\;", r"\quad", r"\qquad", r"\!", r"\ "):
        normalized = normalized.replace(command, " ")
    normalized = _SUPERSCRIPT_RUN.sub(
        lambda match: "^" + match.group(0).translate(_SUPERSCRIPT_TRANSLATION),
        normalized,
    )
    normalized = _SUBSCRIPT_RUN.sub(
        lambda match: "_" + match.group(0).translate(_SUBSCRIPT_TRANSLATION),
        normalized,
    )
    # Self-repair stage: any backslash-letter sequence still present after all
    # projections is an unknown LaTeX command.  The renderer repairs it
    # deterministically instead of aborting: braced commands collapse to their
    # inner text, bare commands drop the backslash and keep the command word.
    # Every repair is reported through the render log and the manifest so the
    # model's notation drift stays observable without blocking delivery.
    def _repair(match: re.Match[str]) -> str:
        inner = match.group("inner")
        repaired = inner if inner is not None else match.group("command")
        record = f"\\{match.group('command')}" + (f"{{{inner}}}" if inner is not None else "")
        _record_latex_repair(f"{record} → {repaired}")
        return repaired

    normalized = _UNKNOWN_COMMAND_RE.sub(_repair, normalized)
    return normalized


def _record_latex_repair(repair: str) -> None:
    ledger = _render_repair_ledger.repairs
    if repair not in ledger:
        ledger.append(repair)
    logging.getLogger("autoresearch.render").warning("自动修复未消解 LaTeX 命令：%s", repair)


def _tex_escape(value: Any) -> str:
    text = _normalize_latex_math_in_text(_text(value))
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(
        _MATH_SYMBOLS.get(character, replacements.get(character, character))
        for character in text
    )


def _tex_url_escape(value: str) -> str:
    return value.replace("\\", "/").replace("{", "%7B").replace("}", "%7D").replace(" ", "%20")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compiler_identity() -> str:
    compiler = shutil.which("latexmk") or shutil.which("xelatex")
    return compiler or "missing"


def _tail(text: str, *, limit: int = 2_000) -> str:
    return text.strip()[-limit:]
