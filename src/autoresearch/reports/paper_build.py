"""Build LaTeX paper artifacts from evidence-bound Markdown manuscripts."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from autoresearch.process import windows_no_window_kwargs

from .latex_templates import (
    LatexTemplateDependencyResolution,
    LatexTemplateDependencyStatus,
    LatexTemplateSourceKind,
    LatexTemplateSpec,
    ensure_latex_template_class_available,
    external_latex_templates,
    generic_latex_templates,
)

REQUIRED_PAPER_SECTIONS = (
    "Abstract",
    "Introduction",
    "Related Work",
    "Method",
    "Experiments",
    "Results",
    "Limitations",
    "Conclusion",
    "References",
)
PAPER_MIN_PAGES = 6
PAPER_MIN_WORDS = 2500
PAPER_MIN_TECHNICAL_TERMS = 15
PAPER_MAX_OVERFULL_HBOX_COUNT = 0
PAPER_MAX_OVERFULL_HBOX_POINTS = 0.0
PAPER_MIN_FIGURES = 1
PAPER_MIN_TABLES = 1
PAPER_MIN_BIBLIOGRAPHY_ITEMS = 1
PAPER_SECTION_MIN_WORDS = {
    "Abstract": 80,
    "Introduction": 180,
    "Related Work": 220,
    "Method": 260,
    "Experiments": 260,
    "Results": 220,
    "Limitations": 120,
    "Conclusion": 120,
}
PAPER_TECHNICAL_TERMS = {
    "ablation",
    "algorithm",
    "artifact",
    "baseline",
    "benchmark",
    "calibration",
    "citation",
    "claim",
    "configuration",
    "dataset",
    "evidence",
    "experiment",
    "hash",
    "hypothesis",
    "metric",
    "model",
    "novelty",
    "reproducibility",
    "reproduction",
    "robustness",
    "statistical",
    "validation",
}


class LatexPaperBuildStatus(str, Enum):
    """Outcome for a Markdown-to-LaTeX paper build."""

    COMPILED = "compiled"
    COMPILED_WITH_QUALITY_ISSUES = "compiled_with_quality_issues"
    RENDERED = "rendered"
    MISSING_SECTIONS = "missing_sections"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class LatexPaperQualityReport:
    """Deterministic paper-level quality gate for compiled manuscripts."""

    passed: bool
    page_count: int | None
    min_pages: int
    word_count: int
    min_word_count: int
    technical_term_count: int
    min_technical_terms: int
    section_word_counts: dict[str, int]
    section_min_words: dict[str, int]
    short_sections: tuple[str, ...]
    overfull_hbox_count: int
    max_overfull_hbox_count: int
    max_overfull_hbox_points: float
    max_allowed_overfull_hbox_points: float
    figure_count: int
    min_figures: int
    table_count: int
    min_tables: int
    bibliography_item_count: int
    min_bibliography_items: int
    invalid_reference_label_count: int
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "page_count": self.page_count,
            "min_pages": self.min_pages,
            "word_count": self.word_count,
            "min_word_count": self.min_word_count,
            "technical_term_count": self.technical_term_count,
            "min_technical_terms": self.min_technical_terms,
            "section_word_counts": self.section_word_counts,
            "section_min_words": self.section_min_words,
            "short_sections": list(self.short_sections),
            "overfull_hbox_count": self.overfull_hbox_count,
            "max_overfull_hbox_count": self.max_overfull_hbox_count,
            "max_overfull_hbox_points": self.max_overfull_hbox_points,
            "max_allowed_overfull_hbox_points": self.max_allowed_overfull_hbox_points,
            "figure_count": self.figure_count,
            "min_figures": self.min_figures,
            "table_count": self.table_count,
            "min_tables": self.min_tables,
            "bibliography_item_count": self.bibliography_item_count,
            "min_bibliography_items": self.min_bibliography_items,
            "invalid_reference_label_count": self.invalid_reference_label_count,
            "failures": list(self.failures),
        }


@dataclass(frozen=True)
class LatexPaperBuildArtifact:
    """Generated paper-level LaTeX artifact summary."""

    status: LatexPaperBuildStatus
    generated_at: str
    template: LatexTemplateSpec
    source_markdown_path: str
    tex_path: str | None
    pdf_path: str | None
    log_path: str
    markdown_path: str
    json_path: str
    vault_markdown_path: str | None
    missing_sections: tuple[str, ...]
    engine: str | None
    command: tuple[str, ...]
    dependency_resolution: LatexTemplateDependencyResolution
    quality: LatexPaperQualityReport
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "generated_at": self.generated_at,
            "template": self.template.to_dict(),
            "source_markdown_path": self.source_markdown_path,
            "tex_path": self.tex_path,
            "pdf_path": self.pdf_path,
            "log_path": self.log_path,
            "markdown_path": self.markdown_path,
            "json_path": self.json_path,
            "vault_markdown_path": self.vault_markdown_path,
            "missing_sections": list(self.missing_sections),
            "engine": self.engine,
            "command": list(self.command),
            "dependency_resolution": self.dependency_resolution.to_dict(),
            "paper_quality": self.quality.to_dict(),
            "reason": self.reason,
        }


def build_latex_paper_from_markdown(
    markdown_path: Path | str,
    output_dir: Path | str,
    *,
    template_id: str = "generic-article-one-column",
    title: str | None = None,
    authors: tuple[str, ...] = ("AI-Researcher",),
    compile_pdf: bool = True,
    require_complete_sections: bool = True,
    vault_root: Path | str | None = None,
    project_id: str | None = None,
    timeout_seconds: int = 60,
) -> LatexPaperBuildArtifact:
    """Convert an evidence-bound Markdown manuscript into a LaTeX/PDF artifact."""

    source_path = Path(markdown_path).resolve()
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    template = _template_by_id(template_id)
    generated_at = datetime.now(timezone.utc).isoformat()
    json_path = root / "paper-build.json"
    summary_path = root / "paper-build.md"
    tex_path = root / "main.tex"
    log_path = root / "compile.log"
    source_markdown = source_path.read_text(encoding="utf-8")
    sections = _extract_paper_sections(source_markdown)
    missing_sections = tuple(
        section for section in REQUIRED_PAPER_SECTIONS if not sections.get(section)
    )
    paper_title = title or _extract_markdown_title(source_markdown) or "AI-Researcher Paper"
    tex_path.write_text(
        _render_markdown_sections_as_latex(
            template,
            title=paper_title,
            authors=authors,
            sections=sections,
            source_dir=source_path.parent,
            output_dir=root,
        ),
        encoding="utf-8",
    )

    status = LatexPaperBuildStatus.RENDERED
    reason: str | None = None
    pdf_path: Path | None = None
    command: tuple[str, ...] = ()
    engine_name: str | None = None
    dependency_resolution = _default_dependency_resolution(template)
    if missing_sections and require_complete_sections:
        status = LatexPaperBuildStatus.MISSING_SECTIONS
        reason = "missing required paper sections: " + ", ".join(missing_sections)
        log_path.write_text(reason + "\n", encoding="utf-8")
    elif not compile_pdf:
        status = LatexPaperBuildStatus.RENDERED
        reason = "compile_pdf disabled"
        log_path.write_text(reason + "\n", encoding="utf-8")
    else:
        dependency_resolution = ensure_latex_template_class_available(
            template,
            root,
            timeout_seconds=timeout_seconds,
        )
        if dependency_resolution.status is LatexTemplateDependencyStatus.UNAVAILABLE:
            status = LatexPaperBuildStatus.SOURCE_UNAVAILABLE
            reason = dependency_resolution.message
            log_path.write_text(reason + "\n", encoding="utf-8")
        else:
            engine = _select_latex_engine()
            if engine is None:
                status = LatexPaperBuildStatus.SKIPPED
                reason = "no LaTeX engine found on PATH"
                log_path.write_text(reason + "\n", encoding="utf-8")
            else:
                command_list = _compile_command(engine, tex_path)
                command = _recorded_compile_command(command_list)
                engine_name = Path(engine).name
                status, pdf_path, reason = _compile_latex(
                    tex_path,
                    log_path,
                    command_list,
                    timeout_seconds=timeout_seconds,
                )
    quality = _build_quality_report(
        sections,
        source_markdown,
        pdf_path,
        log_path,
    )
    if status is LatexPaperBuildStatus.COMPILED and not quality.passed:
        status = LatexPaperBuildStatus.COMPILED_WITH_QUALITY_ISSUES
        reason = "paper quality gate failed: " + ", ".join(quality.failures)

    artifact = LatexPaperBuildArtifact(
        status=status,
        generated_at=generated_at,
        template=template,
        source_markdown_path=_artifact_path_text(source_path),
        tex_path=_artifact_path_text(tex_path),
        pdf_path=_artifact_path_text(pdf_path) if pdf_path is not None else None,
        log_path=_artifact_path_text(log_path),
        markdown_path=_artifact_path_text(summary_path),
        json_path=_artifact_path_text(json_path),
        vault_markdown_path=None,
        missing_sections=missing_sections,
        engine=engine_name,
        command=command,
        dependency_resolution=dependency_resolution,
        quality=quality,
        reason=reason,
    )
    summary_markdown = _render_build_markdown(artifact)
    json_path.write_text(json.dumps(artifact.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    summary_path.write_text(summary_markdown, encoding="utf-8")
    vault_path = _write_vault_summary(summary_markdown, vault_root, project_id)
    if vault_path is not None:
        artifact = LatexPaperBuildArtifact(
            status=artifact.status,
            generated_at=artifact.generated_at,
            template=artifact.template,
            source_markdown_path=artifact.source_markdown_path,
            tex_path=artifact.tex_path,
            pdf_path=artifact.pdf_path,
            log_path=artifact.log_path,
            markdown_path=artifact.markdown_path,
            json_path=artifact.json_path,
            vault_markdown_path=_artifact_path_text(vault_path),
            missing_sections=artifact.missing_sections,
            engine=artifact.engine,
            command=artifact.command,
            dependency_resolution=artifact.dependency_resolution,
            quality=artifact.quality,
            reason=artifact.reason,
        )
        summary_markdown = _render_build_markdown(artifact)
        json_path.write_text(
            json.dumps(artifact.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        summary_path.write_text(summary_markdown, encoding="utf-8")
        vault_path.write_text(summary_markdown, encoding="utf-8")
    return artifact


def _artifact_path_text(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _template_by_id(template_id: str) -> LatexTemplateSpec:
    for template in (*generic_latex_templates(), *external_latex_templates()):
        if template.id == template_id:
            return template
    msg = f"unknown LaTeX template id: {template_id}"
    raise ValueError(msg)


def _default_dependency_resolution(template: LatexTemplateSpec) -> LatexTemplateDependencyResolution:
    class_file = template.class_file or f"{template.document_class}.cls"
    if template.source_kind is LatexTemplateSourceKind.BUILT_IN_GENERIC:
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.NOT_REQUIRED,
            checked_at=datetime.now(timezone.utc).isoformat(),
            class_file=class_file,
            message="built-in generic templates do not require external class recovery",
        )
    return LatexTemplateDependencyResolution(
        status=LatexTemplateDependencyStatus.SKIPPED,
        checked_at=datetime.now(timezone.utc).isoformat(),
        class_file=class_file,
        message="paper-build did not reach the external template dependency gate",
    )


def _extract_markdown_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return None


def _extract_paper_sections(markdown: str) -> dict[str, str]:
    headings = {
        section.casefold(): section
        for section in REQUIRED_PAPER_SECTIONS
    }
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            heading = match.group(1).strip().casefold()
            current = headings.get(heading)
            if current is not None:
                sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {
        section: "\n".join(lines).strip()
        for section, lines in sections.items()
        if "\n".join(lines).strip()
    }


def _render_markdown_sections_as_latex(
    template: LatexTemplateSpec,
    *,
    title: str,
    authors: tuple[str, ...],
    sections: dict[str, str],
    source_dir: Path,
    output_dir: Path,
) -> str:
    class_options = (
        f"[{','.join(template.class_options)}]"
        if template.class_options
        else ""
    )
    lines = [
        rf"\documentclass{class_options}{{{template.document_class}}}",
        r"\title{" + _latex_escape(title) + "}",
        r"\author{" + _latex_escape(", ".join(authors)) + "}",
        r"\date{}",
        r"\usepackage{url}",
        r"\usepackage{graphicx}",
        r"\emergencystretch=3em",
        *template.preamble_lines,
        r"\begin{document}",
    ]
    abstract = sections.get("Abstract", "")
    abstract_lines = [
        r"\begin{abstract}",
        *_markdown_text_to_latex_lines(abstract, source_dir=source_dir, output_dir=output_dir),
        r"\end{abstract}",
        "",
    ]
    if template.abstract_before_maketitle:
        lines.extend(abstract_lines)
        lines.append(r"\maketitle")
    else:
        lines.append(r"\maketitle")
        lines.extend(abstract_lines)
    lines.append("")
    for section in REQUIRED_PAPER_SECTIONS:
        if section == "Abstract":
            continue
        body = sections.get(section)
        if not body:
            continue
        if section == "References":
            lines.extend(
                _markdown_references_to_latex_lines(
                    body,
                    source_dir=source_dir,
                    output_dir=output_dir,
                )
            )
        else:
            lines.extend([rf"\section{{{_latex_escape(section)}}}"])
            lines.extend(
                _markdown_text_to_latex_lines(
                    body,
                    source_dir=source_dir,
                    output_dir=output_dir,
                )
            )
        lines.append("")
    lines.extend([r"\end{document}", ""])
    return "\n".join(lines)


def _build_quality_report(
    sections: dict[str, str],
    source_markdown: str,
    pdf_path: Path | None,
    log_path: Path,
) -> LatexPaperQualityReport:
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    page_count = _pdf_page_count(pdf_path, log_text)
    manuscript_text = "\n".join(
        body for section, body in sections.items() if section != "References"
    )
    word_count = _word_count(manuscript_text)
    technical_terms = _technical_terms(source_markdown)
    section_word_counts = {
        section: _word_count(sections.get(section, ""))
        for section in PAPER_SECTION_MIN_WORDS
    }
    short_sections = tuple(
        section
        for section, min_words in PAPER_SECTION_MIN_WORDS.items()
        if section_word_counts.get(section, 0) < min_words
    )
    overfull_points = _overfull_hbox_points(log_text)
    overfull_count = len(overfull_points)
    max_overfull_points = max(overfull_points) if overfull_points else 0.0
    figure_count = _markdown_figure_count(source_markdown)
    table_count = _markdown_table_count(source_markdown)
    references_body = sections.get("References", "")
    bibliography_item_count = _bibliography_item_count(references_body)
    invalid_reference_label_count = _invalid_reference_label_count(references_body)
    failures: list[str] = []
    if page_count is None or page_count < PAPER_MIN_PAGES:
        failures.append("page_count")
    if word_count < PAPER_MIN_WORDS:
        failures.append("word_count")
    if len(technical_terms) < PAPER_MIN_TECHNICAL_TERMS:
        failures.append("technical_depth")
    if short_sections:
        failures.append("section_depth")
    if (
        overfull_count > PAPER_MAX_OVERFULL_HBOX_COUNT
        or max_overfull_points > PAPER_MAX_OVERFULL_HBOX_POINTS
    ):
        failures.append("layout_overflow")
    if figure_count < PAPER_MIN_FIGURES:
        failures.append("figure_coverage")
    if table_count < PAPER_MIN_TABLES:
        failures.append("table_coverage")
    if bibliography_item_count < PAPER_MIN_BIBLIOGRAPHY_ITEMS:
        failures.append("bibliography_depth")
    if invalid_reference_label_count:
        failures.append("reference_format")
    return LatexPaperQualityReport(
        passed=not failures,
        page_count=page_count,
        min_pages=PAPER_MIN_PAGES,
        word_count=word_count,
        min_word_count=PAPER_MIN_WORDS,
        technical_term_count=len(technical_terms),
        min_technical_terms=PAPER_MIN_TECHNICAL_TERMS,
        section_word_counts=section_word_counts,
        section_min_words=dict(PAPER_SECTION_MIN_WORDS),
        short_sections=short_sections,
        overfull_hbox_count=overfull_count,
        max_overfull_hbox_count=PAPER_MAX_OVERFULL_HBOX_COUNT,
        max_overfull_hbox_points=max_overfull_points,
        max_allowed_overfull_hbox_points=PAPER_MAX_OVERFULL_HBOX_POINTS,
        figure_count=figure_count,
        min_figures=PAPER_MIN_FIGURES,
        table_count=table_count,
        min_tables=PAPER_MIN_TABLES,
        bibliography_item_count=bibliography_item_count,
        min_bibliography_items=PAPER_MIN_BIBLIOGRAPHY_ITEMS,
        invalid_reference_label_count=invalid_reference_label_count,
        failures=tuple(failures),
    )


def _pdf_page_count(pdf_path: Path | None, log_text: str) -> int | None:
    if pdf_path is not None and pdf_path.exists() and (pdfinfo := shutil.which("pdfinfo")):
        try:
            completed = subprocess.run(
                [pdfinfo, pdf_path.as_posix()],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                **windows_no_window_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode == 0:
            match = re.search(r"^Pages:\s*(\d+)\s*$", completed.stdout, flags=re.MULTILINE)
            if match:
                return int(match.group(1))
    match = re.search(r"Output written on .+?\((\d+) pages?,", log_text)
    if match:
        return int(match.group(1))
    return None


def _overfull_hbox_points(log_text: str) -> tuple[float, ...]:
    return tuple(
        float(match)
        for match in re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide\)", log_text)
    )


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z][A-Za-z0-9-]*\b", text))


def _technical_terms(text: str) -> set[str]:
    words = {word.casefold() for word in re.findall(r"\b[A-Za-z][A-Za-z0-9-]*\b", text)}
    return words & PAPER_TECHNICAL_TERMS


def _markdown_figure_count(markdown: str) -> int:
    return len(re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown))


def _markdown_table_count(markdown: str) -> int:
    lines = markdown.splitlines()
    count = 0
    index = 0
    while index < len(lines):
        if _starts_markdown_table(lines, index):
            count += 1
            _block, index = _collect_markdown_table(lines, index)
            continue
        index += 1
    return count


def _bibliography_item_count(references_body: str) -> int:
    count = 0
    for line in references_body.splitlines():
        label_match = re.match(r"^[-*]\s+\[([^\]]+)\]\s+(.+?)\s*$", line.strip())
        cite_match = re.match(r"^[-*]\s+@[A-Za-z0-9:_-]+:\s+.+?\s*$", line.strip())
        if (
            label_match
            and not _is_nonbibliographic_reference_label(label_match.group(1))
        ) or cite_match:
            count += 1
    return count


def _invalid_reference_label_count(references_body: str) -> int:
    count = 0
    for line in references_body.splitlines():
        match = re.match(r"^[-*]\s+\[([^\]]+)\]\s+.+?\s*$", line.strip())
        if match and _is_nonbibliographic_reference_label(match.group(1)):
            count += 1
    return count


def _markdown_text_to_latex_lines(
    text: str,
    *,
    source_dir: Path,
    output_dir: Path,
) -> list[str]:
    lines: list[str] = []
    raw_lines = text.splitlines()
    index = 0
    while index < len(raw_lines):
        if _starts_markdown_table(raw_lines, index):
            table_block, index = _collect_markdown_table(raw_lines, index)
            lines.extend(_markdown_table_to_latex_lines(table_block))
            continue
        raw_line = raw_lines[index]
        index += 1
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        image = _markdown_image_match(line)
        if image is not None:
            alt_text, asset_path = image
            lines.extend(
                _markdown_image_to_latex_lines(
                    alt_text,
                    asset_path,
                    source_dir=source_dir,
                    output_dir=output_dir,
                )
            )
            continue
        subheading = re.match(r"^###\s+(.+?)\s*$", line)
        if subheading:
            lines.append(rf"\subsection{{{_latex_inline(subheading.group(1))}}}")
            continue
        lines.append(_latex_inline(_strip_markdown_markup(line)))
    while lines and lines[-1] == "":
        lines.pop()
    return lines or [""]


def _markdown_references_to_latex_lines(
    text: str,
    *,
    source_dir: Path,
    output_dir: Path,
) -> list[str]:
    entries: list[tuple[str, str]] = []
    note_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^[-*]\s+\[([^\]]+)\]\s+(.+?)\s*$", line)
        if match:
            key = _safe_bibitem_key(match.group(1))
            if _is_nonbibliographic_reference_label(match.group(1)):
                note_lines.append(match.group(2))
                continue
            entries.append((key, match.group(2)))
            continue
        match = re.match(r"^[-*]\s+@([A-Za-z0-9:_-]+):\s+(.+?)\s*$", line)
        if match:
            entries.append((_safe_bibitem_key(match.group(1)), match.group(2)))
            continue
        if line.startswith("- ") or line.startswith("* "):
            entries.append((f"ref-{len(entries) + 1}", line[2:].strip()))
            continue
        note_lines.append(line)
    lines: list[str] = []
    if note_lines and not entries:
        lines.extend(
            _markdown_text_to_latex_lines(
                "\n".join(note_lines),
                source_dir=source_dir,
                output_dir=output_dir,
            )
        )
    if entries:
        lines.append(r"\begin{thebibliography}{99}")
        for key, body in entries:
            lines.append(rf"\bibitem{{{key}}} {_latex_inline_with_urls(_strip_markdown_markup(body))}")
        lines.append(r"\end{thebibliography}")
    return lines or ["No formal bibliography entries were generated."]


def _strip_markdown_markup(line: str) -> str:
    line = re.sub(r"^[-*]\s+", "", line)
    line = re.sub(r"`([^`]+)`", r"\1", line)
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    return line


def _latex_inline(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"\[@([A-Za-z0-9:_-]+)\]", text):
        parts.append(_latex_escape(text[cursor:match.start()]))
        parts.append(rf"\cite{{{_safe_bibitem_key(match.group(1))}}}")
        cursor = match.end()
    parts.append(_latex_escape(text[cursor:]))
    return "".join(parts)


def _latex_inline_with_urls(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"https?://[^\s.)]+[^\s.);,]", text):
        parts.append(_latex_inline(text[cursor:match.start()]))
        parts.append(rf"\url{{{match.group(0)}}}")
        cursor = match.end()
    parts.append(_latex_inline(text[cursor:]))
    return "".join(parts)


def _markdown_image_match(line: str) -> tuple[str, str] | None:
    match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _markdown_image_to_latex_lines(
    alt_text: str,
    asset_path: str,
    *,
    source_dir: Path,
    output_dir: Path,
) -> list[str]:
    resolved = _resolve_markdown_asset_path(asset_path, source_dir=source_dir, output_dir=output_dir)
    return [
        r"\begin{figure}[t]",
        r"\centering",
        rf"\includegraphics[width=0.88\linewidth]{{{resolved}}}",
        rf"\caption{{{_latex_inline(alt_text or 'Source-backed figure')}}}",
        r"\end{figure}",
    ]


def _resolve_markdown_asset_path(
    asset_path: str,
    *,
    source_dir: Path,
    output_dir: Path,
) -> str:
    cleaned = asset_path.strip().strip("\"'")
    if re.match(r"^[a-z]+://", cleaned, flags=re.IGNORECASE):
        return cleaned
    source = Path(cleaned)
    if not source.is_absolute():
        source = source_dir / source
    try:
        return os.path.relpath(source.resolve(), start=output_dir.resolve()).replace("\\", "/")
    except ValueError:
        return source.resolve().as_posix()


def _starts_markdown_table(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return _is_table_row(lines[index]) and _is_table_separator(lines[index + 1])


def _collect_markdown_table(lines: list[str], index: int) -> tuple[list[str], int]:
    block: list[str] = []
    while index < len(lines) and _is_table_row(lines[index]):
        block.append(lines[index].strip())
        index += 1
    return block, index


def _markdown_table_to_latex_lines(block: list[str]) -> list[str]:
    if len(block) < 2:
        return []
    rows = [_markdown_table_cells(row) for row in block]
    header = rows[0]
    body_rows = rows[2:]
    column_count = len(header)
    latex_lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\caption{Source-backed data table}",
        rf"\begin{{tabular}}{{{_table_column_spec(column_count)}}}",
        r"\hline",
        " & ".join(_latex_inline(_strip_markdown_markup(cell)) for cell in header) + r" \\",
        r"\hline",
    ]
    for row in body_rows:
        normalized = [*row, *([""] * max(column_count - len(row), 0))][:column_count]
        latex_lines.append(
            " & ".join(_latex_inline(_strip_markdown_markup(cell)) for cell in normalized)
            + r" \\"
        )
    latex_lines.extend([r"\hline", r"\end{tabular}", r"\end{table}"])
    return latex_lines


def _table_column_spec(column_count: int) -> str:
    width = "0.28" if column_count <= 3 else f"{0.92 / max(column_count, 1):.2f}"
    return "|" + "|".join([rf"p{{{width}\linewidth}}"] * max(column_count, 1)) + "|"


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _is_table_separator(line: str) -> bool:
    cells = _markdown_table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _markdown_table_cells(line: str) -> list[str]:
    return [cell.strip().replace(r"\|", "|") for cell in line.strip().strip("|").split("|")]


def _safe_bibitem_key(key: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9:_-]+", "-", key.strip()).strip("-")
    return cleaned or "unknown-reference"


def _is_nonbibliographic_reference_label(label: str) -> bool:
    normalized = label.casefold().strip()
    return normalized in {
        "cycle summary",
        "run record",
        "validation",
        "evidence map",
        "literature refresh",
        "citation package",
        "citation package note",
        "related-work inspection",
        "similarity check",
        "reproduction check",
        "publication audit",
        "paper build",
        "verified literature references",
    }


def _compile_latex(
    tex_path: Path,
    log_path: Path,
    command: list[str],
    *,
    timeout_seconds: int,
) -> tuple[LatexPaperBuildStatus, Path | None, str | None]:
    try:
        completed = subprocess.run(
            command,
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            **windows_no_window_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(str(exc), encoding="utf-8")
        return LatexPaperBuildStatus.FAILED, None, f"compile timed out after {timeout_seconds}s"
    log_path.write_text(
        "STDOUT:\n" + completed.stdout + "\nSTDERR:\n" + completed.stderr,
        encoding="utf-8",
    )
    pdf_path = tex_path.with_suffix(".pdf")
    if completed.returncode == 0 and pdf_path.exists():
        return LatexPaperBuildStatus.COMPILED, pdf_path, None
    return (
        LatexPaperBuildStatus.FAILED,
        None,
        f"LaTeX compile failed with exit code {completed.returncode}",
    )


def _render_build_markdown(artifact: LatexPaperBuildArtifact) -> str:
    lines = [
        "# Paper Build",
        "",
        f"- Generated at: `{artifact.generated_at}`",
        f"- Source Markdown: `{artifact.source_markdown_path}`",
        f"- Template: `{artifact.template.id}`",
        f"- Status: `{artifact.status.value}`",
        f"- TeX: `{artifact.tex_path or 'none'}`",
        f"- PDF: `{artifact.pdf_path or 'none'}`",
        f"- Log: `{artifact.log_path}`",
        f"- JSON: `{artifact.json_path}`",
        f"- Vault copy: `{artifact.vault_markdown_path or 'not written'}`",
        f"- Dependency recovery: `{artifact.dependency_resolution.status.value}`",
        f"- Dependency class: `{artifact.dependency_resolution.class_file or 'none'}`",
        f"- Dependency message: `{artifact.dependency_resolution.message}`",
        f"- Dependency artifact: `{artifact.dependency_resolution.artifact_path or 'none'}`",
        f"- Reason: `{artifact.reason or 'None'}`",
        f"- Quality passed: `{str(artifact.quality.passed).lower()}`",
        f"- Page count: `{artifact.quality.page_count or 'unknown'}` / minimum `{artifact.quality.min_pages}`",
        f"- Word count: `{artifact.quality.word_count}` / minimum `{artifact.quality.min_word_count}`",
        (
            f"- Technical terms: `{artifact.quality.technical_term_count}` / "
            f"minimum `{artifact.quality.min_technical_terms}`"
        ),
        (
            f"- Overfull hbox: `{artifact.quality.overfull_hbox_count}` / "
            f"maximum `{artifact.quality.max_overfull_hbox_count}`; "
            f"max width `{artifact.quality.max_overfull_hbox_points:.3f}pt`"
        ),
        f"- Figures: `{artifact.quality.figure_count}` / minimum `{artifact.quality.min_figures}`",
        f"- Data tables: `{artifact.quality.table_count}` / minimum `{artifact.quality.min_tables}`",
        (
            f"- Bibliography items: `{artifact.quality.bibliography_item_count}` / "
            f"minimum `{artifact.quality.min_bibliography_items}`"
        ),
        f"- Invalid reference labels: `{artifact.quality.invalid_reference_label_count}`",
        "",
        "## Missing Sections",
        "",
    ]
    if artifact.missing_sections:
        lines.extend(f"- `{section}`" for section in artifact.missing_sections)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Quality Gate",
            "",
        ]
    )
    if artifact.quality.failures:
        lines.extend(f"- `{failure}`" for failure in artifact.quality.failures)
    else:
        lines.append("- None")
    if artifact.quality.short_sections:
        lines.extend(
            [
                "",
                "## Short Sections",
                "",
            ]
        )
        for section in artifact.quality.short_sections:
            lines.append(
                f"- `{section}`: `{artifact.quality.section_word_counts[section]}` / "
                f"minimum `{artifact.quality.section_min_words[section]}` words"
            )
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- Process data and evidence summaries remain Markdown in the Obsidian vault.",
            "- The paper-level artifact is release-ready only when status is `compiled` and quality passed is `true`.",
            "- Missing paper sections stop compilation instead of being filled with invented content.",
            "- Missing external LaTeX classes trigger recorded TeX Live or official archive recovery before the build is blocked.",
            "- Thin manuscripts, shallow technical sections, or LaTeX overfull boxes are blockers, not polish notes.",
            "- Missing source-backed figures, missing data-analysis tables, missing formal bibliography entries, or operational evidence labels inside References are release blockers.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_vault_summary(
    markdown: str,
    vault_root: Path | str | None,
    project_id: str | None,
) -> Path | None:
    if vault_root is None or not project_id:
        return None
    target = Path(vault_root) / "projects" / project_id / "paper" / "paper-build.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target


def _template_class_available(template: LatexTemplateSpec) -> bool:
    class_file = template.class_file or f"{template.document_class}.cls"
    try:
        completed = subprocess.run(
            ["kpsewhich", class_file],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            **windows_no_window_kwargs(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and bool(completed.stdout.strip())


def _select_latex_engine() -> str | None:
    return shutil.which("pdflatex") or shutil.which("tectonic")


def _compile_command(engine: str, tex_path: Path) -> list[str]:
    executable = Path(engine).name.casefold()
    if executable.startswith("pdflatex"):
        return [engine, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    return [engine, tex_path.name]


def _recorded_compile_command(command: list[str]) -> tuple[str, ...]:
    if not command:
        return ()
    recorded = list(command)
    executable = Path(recorded[0])
    if executable.is_absolute():
        recorded[0] = executable.name
    return tuple(recorded)


def _latex_escape(text: str) -> str:
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
    return "".join(replacements.get(character, character) for character in text)
