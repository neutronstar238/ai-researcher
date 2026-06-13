"""Build LaTeX paper artifacts from evidence-bound Markdown manuscripts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .latex_templates import (
    LatexTemplateSourceKind,
    LatexTemplateSpec,
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
        ),
        encoding="utf-8",
    )

    status = LatexPaperBuildStatus.RENDERED
    reason: str | None = None
    pdf_path: Path | None = None
    command: tuple[str, ...] = ()
    engine_name: str | None = None
    if missing_sections and require_complete_sections:
        status = LatexPaperBuildStatus.MISSING_SECTIONS
        reason = "missing required paper sections: " + ", ".join(missing_sections)
        log_path.write_text(reason + "\n", encoding="utf-8")
    elif template.source_kind is LatexTemplateSourceKind.EXTERNAL_FETCHED and not _template_class_available(template):
        status = LatexPaperBuildStatus.SOURCE_UNAVAILABLE
        reason = f"template class {template.class_file or template.document_class + '.cls'} is unavailable"
        log_path.write_text(reason + "\n", encoding="utf-8")
    elif not compile_pdf:
        status = LatexPaperBuildStatus.RENDERED
        reason = "compile_pdf disabled"
        log_path.write_text(reason + "\n", encoding="utf-8")
    else:
        engine = _select_latex_engine()
        if engine is None:
            status = LatexPaperBuildStatus.SKIPPED
            reason = "no LaTeX engine found on PATH"
            log_path.write_text(reason + "\n", encoding="utf-8")
        else:
            command_list = _compile_command(engine, tex_path)
            command = tuple(command_list)
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
        source_markdown_path=source_path.as_posix(),
        tex_path=tex_path.as_posix(),
        pdf_path=pdf_path.as_posix() if pdf_path is not None else None,
        log_path=log_path.as_posix(),
        markdown_path=summary_path.as_posix(),
        json_path=json_path.as_posix(),
        vault_markdown_path=None,
        missing_sections=missing_sections,
        engine=engine_name,
        command=command,
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
            vault_markdown_path=vault_path.as_posix(),
            missing_sections=artifact.missing_sections,
            engine=artifact.engine,
            command=artifact.command,
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


def _template_by_id(template_id: str) -> LatexTemplateSpec:
    for template in (*generic_latex_templates(), *external_latex_templates()):
        if template.id == template_id:
            return template
    msg = f"unknown LaTeX template id: {template_id}"
    raise ValueError(msg)


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
        r"\emergencystretch=3em",
        *template.preamble_lines,
        r"\begin{document}",
    ]
    abstract = sections.get("Abstract", "")
    abstract_lines = [
        r"\begin{abstract}",
        *_markdown_text_to_latex_lines(abstract),
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
        lines.extend([rf"\section{{{_latex_escape(section)}}}"])
        lines.extend(_markdown_text_to_latex_lines(body))
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


def _markdown_text_to_latex_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        lines.append(_latex_escape(_strip_markdown_markup(line)))
    while lines and lines[-1] == "":
        lines.pop()
    return lines or [""]


def _strip_markdown_markup(line: str) -> str:
    line = re.sub(r"^[-*]\s+", "", line)
    line = re.sub(r"`([^`]+)`", r"\1", line)
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    return line


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
            "- Thin manuscripts, shallow technical sections, or LaTeX overfull boxes are blockers, not polish notes.",
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
