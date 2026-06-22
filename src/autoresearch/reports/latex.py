"""Generate LaTeX paper skeletons from validated evidence."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoresearch.process import windows_no_window_kwargs
from autoresearch.evidence import EvidenceGraph, EvidenceGraphError
from autoresearch.schemas import ValidationStatus

SECTION_TITLES = {
    "abstract": "Abstract",
    "introduction": "Introduction",
    "related_work": "Related Work",
    "method": "Method",
    "experiments": "Experiments",
    "results": "Results",
    "limitations": "Limitations",
    "conclusion": "Conclusion",
}
SECTION_ORDER = tuple(SECTION_TITLES)
VALID_EVIDENCE_STATUSES = {ValidationStatus.PASSED, ValidationStatus.WARNING}


class LatexGenerationError(RuntimeError):
    """Raised when a LaTeX draft cannot be generated."""


class LatexCompilationError(LatexGenerationError):
    """Raised when the generated LaTeX skeleton does not compile."""


@dataclass(frozen=True)
class LatexDraftContext:
    """Evidence-backed inputs for a LaTeX skeleton."""

    project_id: str
    title: str
    authors: list[str]
    evidence_graph: EvidenceGraph
    section_claim_ids: Mapping[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class LatexDraftArtifact:
    """Generated LaTeX draft paths and placeholder status."""

    tex_path: str
    pdf_path: str | None
    placeholder_sections: tuple[str, ...]
    section_claim_ids: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tex_path": self.tex_path,
            "pdf_path": self.pdf_path,
            "placeholder_sections": list(self.placeholder_sections),
            "section_claim_ids": self.section_claim_ids,
        }


def generate_latex_skeleton(
    context: LatexDraftContext,
    output_dir: Path | str,
    *,
    filename: str = "main.tex",
    compile_pdf: bool = False,
) -> LatexDraftArtifact:
    """Generate a compilable LaTeX skeleton from evidence graph claims."""

    _validate_context(context)
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    tex_path = output_path / filename
    body, placeholder_sections = _render_latex(context)
    tex_path.write_text(body, encoding="utf-8")
    pdf_path = _compile_latex(tex_path) if compile_pdf else None
    return LatexDraftArtifact(
        tex_path=tex_path.as_posix(),
        pdf_path=pdf_path.as_posix() if pdf_path is not None else None,
        placeholder_sections=tuple(placeholder_sections),
        section_claim_ids={
            section: list(context.section_claim_ids.get(section, []))
            for section in SECTION_ORDER
        },
    )


def _validate_context(context: LatexDraftContext) -> None:
    if not context.project_id:
        msg = "project_id is required"
        raise LatexGenerationError(msg)
    if not context.title:
        msg = "title is required"
        raise LatexGenerationError(msg)
    if not context.authors:
        msg = "at least one author is required"
        raise LatexGenerationError(msg)
    unknown_sections = set(context.section_claim_ids) - set(SECTION_ORDER)
    if unknown_sections:
        msg = "unknown LaTeX paper section(s): " + ", ".join(sorted(unknown_sections))
        raise LatexGenerationError(msg)


def _render_latex(context: LatexDraftContext) -> tuple[str, list[str]]:
    placeholder_sections: list[str] = []
    lines = [
        r"\documentclass{article}",
        r"\title{" + _latex_escape(context.title) + "}",
        r"\author{" + _latex_escape(", ".join(context.authors)) + "}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        "",
        r"\begin{abstract}",
    ]
    abstract_lines, has_abstract_placeholder = _section_lines(context, "abstract")
    lines.extend(abstract_lines)
    lines.extend([r"\end{abstract}", ""])
    if has_abstract_placeholder:
        placeholder_sections.append("abstract")

    for section in SECTION_ORDER:
        if section == "abstract":
            continue
        section_lines, has_placeholder = _section_lines(context, section)
        lines.extend([rf"\section{{{SECTION_TITLES[section]}}}", *section_lines, ""])
        if has_placeholder:
            placeholder_sections.append(section)

    lines.append(r"\end{document}")
    lines.append("")
    return "\n".join(lines), placeholder_sections


def _section_lines(
    context: LatexDraftContext,
    section: str,
) -> tuple[list[str], bool]:
    claim_ids = context.section_claim_ids.get(section, [])
    if not claim_ids:
        return [_placeholder(f"Missing evidence for {SECTION_TITLES[section]}.")], True

    lines: list[str] = []
    has_placeholder = False
    for claim_id in claim_ids:
        claim_lines, claim_has_placeholder = _claim_lines(context.evidence_graph, claim_id)
        lines.extend(claim_lines)
        lines.append("")
        has_placeholder = has_placeholder or claim_has_placeholder
    while lines and lines[-1] == "":
        lines.pop()
    return lines, has_placeholder


def _claim_lines(graph: EvidenceGraph, claim_id: str) -> tuple[list[str], bool]:
    try:
        traces = graph.trace_claim(claim_id)
    except EvidenceGraphError:
        return [_placeholder(f"Missing claim {claim_id}.")], True

    claim = graph.claims[claim_id]
    valid_traces = [
        trace
        for trace in traces
        if trace.evidence.supports_claim
        and trace.validation_status in VALID_EVIDENCE_STATUSES
    ]
    if not valid_traces:
        return [
            _latex_escape(claim.statement),
            _placeholder(f"Missing validated evidence for claim {claim_id}."),
        ], True

    lines = [_latex_escape(claim.statement)]
    for trace in valid_traces:
        lines.append(
            "Evidence: "
            + _latex_escape(trace.evidence.summary)
            + " Source: "
            + _latex_escape(trace.source.title)
            + " Artifact: "
            + _latex_escape(trace.artifact.uri)
            + "."
        )
    return lines, False


def _placeholder(message: str) -> str:
    return r"\textbf{TODO: " + _latex_escape(message) + "}"


def _compile_latex(tex_path: Path) -> Path:
    pdflatex = shutil.which("pdflatex")
    if pdflatex is None:
        msg = "pdflatex is not available on PATH"
        raise LatexCompilationError(msg)
    command = [
        pdflatex,
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]
    result = subprocess.run(
        command,
        cwd=tex_path.parent,
        capture_output=True,
        text=True,
        check=False,
        **windows_no_window_kwargs(),
    )
    pdf_path = tex_path.with_suffix(".pdf")
    if result.returncode != 0 or not pdf_path.exists():
        msg = (
            "pdflatex failed for "
            f"{tex_path.as_posix()}: {result.stdout}\n{result.stderr}"
        )
        raise LatexCompilationError(msg)
    return pdf_path


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
