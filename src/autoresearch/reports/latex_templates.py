"""LaTeX template compatibility smoke tests for paper delivery."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class LatexTemplateSourceKind(str, Enum):
    """Where a template specification comes from."""

    BUILT_IN_GENERIC = "built_in_generic"
    EXTERNAL_FETCHED = "external_fetched"


class LatexTemplateCompatibilityStatus(str, Enum):
    """One template smoke-test outcome."""

    COMPILED = "compiled"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class LatexTemplateSpec:
    """One LaTeX paper template target."""

    id: str
    display_name: str
    source_kind: LatexTemplateSourceKind
    document_class: str
    class_options: tuple[str, ...] = ()
    source_url: str | None = None
    license_note: str = "Built-in generic LaTeX article smoke template."

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "source_kind": self.source_kind.value,
            "document_class": self.document_class,
            "class_options": list(self.class_options),
            "source_url": self.source_url,
            "license_note": self.license_note,
        }


@dataclass(frozen=True)
class LatexTemplateCompatibilityResult:
    """Compatibility result for one template."""

    template: LatexTemplateSpec
    status: LatexTemplateCompatibilityStatus
    tex_path: str
    pdf_path: str | None
    log_path: str
    engine: str | None
    command: tuple[str, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template.to_dict(),
            "status": self.status.value,
            "tex_path": self.tex_path,
            "pdf_path": self.pdf_path,
            "log_path": self.log_path,
            "engine": self.engine,
            "command": list(self.command),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LatexTemplateCompatibilityReport:
    """Template compatibility run artifact."""

    generated_at: str
    output_dir: str
    json_path: str
    markdown_path: str
    vault_markdown_path: str | None
    results: tuple[LatexTemplateCompatibilityResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "output_dir": self.output_dir,
            "json_path": self.json_path,
            "markdown_path": self.markdown_path,
            "vault_markdown_path": self.vault_markdown_path,
            "results": [result.to_dict() for result in self.results],
        }


def generic_latex_templates() -> tuple[LatexTemplateSpec, ...]:
    """Return built-in generic journal-style smoke templates."""

    return (
        LatexTemplateSpec(
            id="generic-article-one-column",
            display_name="Generic Article One Column",
            source_kind=LatexTemplateSourceKind.BUILT_IN_GENERIC,
            document_class="article",
            class_options=("11pt",),
        ),
        LatexTemplateSpec(
            id="generic-article-two-column",
            display_name="Generic Article Two Column",
            source_kind=LatexTemplateSourceKind.BUILT_IN_GENERIC,
            document_class="article",
            class_options=("11pt", "twocolumn"),
        ),
    )


def run_latex_template_compatibility(
    output_dir: Path | str,
    *,
    templates: tuple[LatexTemplateSpec, ...] | None = None,
    compile_pdf: bool = True,
    vault_root: Path | str | None = None,
    project_id: str | None = None,
    timeout_seconds: int = 60,
) -> LatexTemplateCompatibilityReport:
    """Render and optionally compile smoke manuscripts for LaTeX templates."""

    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected_templates = templates or generic_latex_templates()
    results = tuple(
        _run_template_smoke(
            root,
            template,
            compile_pdf=compile_pdf,
            timeout_seconds=timeout_seconds,
        )
        for template in selected_templates
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    json_path = root / "latex-template-compatibility.json"
    markdown_path = root / "latex-template-compatibility.md"
    report = LatexTemplateCompatibilityReport(
        generated_at=generated_at,
        output_dir=root.as_posix(),
        json_path=json_path.as_posix(),
        markdown_path=markdown_path.as_posix(),
        vault_markdown_path=None,
        results=results,
    )
    markdown = _render_compatibility_markdown(report)
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    vault_markdown_path = _write_vault_markdown(markdown, vault_root, project_id)
    if vault_markdown_path is not None:
        report = LatexTemplateCompatibilityReport(
            generated_at=report.generated_at,
            output_dir=report.output_dir,
            json_path=report.json_path,
            markdown_path=report.markdown_path,
            vault_markdown_path=vault_markdown_path.as_posix(),
            results=report.results,
        )
        json_path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        final_markdown = _render_compatibility_markdown(report)
        markdown_path.write_text(final_markdown, encoding="utf-8")
        vault_markdown_path.write_text(final_markdown, encoding="utf-8")
    return report


def render_latex_template_smoke(
    template: LatexTemplateSpec,
    *,
    title: str = "AI-Researcher Template Compatibility Smoke",
) -> str:
    """Render a minimal paper manuscript for one LaTeX template."""

    class_options = (
        f"[{','.join(template.class_options)}]"
        if template.class_options
        else ""
    )
    sections = [
        ("Introduction", "This smoke manuscript checks template compatibility for an evidence-first research loop."),
        ("Related Work", "Related work entries remain source-backed in the Obsidian vault and citation pipeline."),
        ("Method", "The method section is generated from executed workflow evidence and reproducibility metadata."),
        ("Experiments", "Experiments must record scripts, data hashes, metrics, validation reports, and logs."),
        ("Results", "Quantitative results must link to evidence artifacts before they can support a claim."),
        ("Limitations", "This smoke manuscript does not claim venue readiness or scientific novelty."),
        ("Conclusion", "A paper-level delivery gate requires this LaTeX source to compile to PDF."),
    ]
    lines = [
        rf"\documentclass{class_options}{{{template.document_class}}}",
        r"\title{" + _latex_escape(title) + "}",
        r"\author{AI-Researcher}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        r"\begin{abstract}",
        (
            "This generated manuscript verifies that AI-Researcher can move from "
            "an Obsidian-readable evidence draft to a LaTeX template artifact."
        ),
        r"\end{abstract}",
        "",
    ]
    for section, body in sections:
        lines.extend([rf"\section{{{section}}}", _latex_escape(body), ""])
    lines.extend(
        [
            r"\begin{thebibliography}{1}",
            r"\bibitem{evidence-vault} AI-Researcher evidence vault record.",
            r"\end{thebibliography}",
            r"\end{document}",
            "",
        ]
    )
    return "\n".join(lines)


def _run_template_smoke(
    root: Path,
    template: LatexTemplateSpec,
    *,
    compile_pdf: bool,
    timeout_seconds: int,
) -> LatexTemplateCompatibilityResult:
    template_dir = root / template.id
    template_dir.mkdir(parents=True, exist_ok=True)
    tex_path = template_dir / "main.tex"
    log_path = template_dir / "compile.log"
    tex_path.write_text(render_latex_template_smoke(template), encoding="utf-8")
    if not compile_pdf:
        reason = "compile_pdf disabled"
        log_path.write_text(reason + "\n", encoding="utf-8")
        return _compatibility_result(
            template,
            LatexTemplateCompatibilityStatus.SKIPPED,
            tex_path,
            log_path,
            None,
            (),
            reason,
        )
    engine = _select_latex_engine()
    if engine is None:
        reason = "no LaTeX engine found on PATH"
        log_path.write_text(reason + "\n", encoding="utf-8")
        return _compatibility_result(
            template,
            LatexTemplateCompatibilityStatus.SKIPPED,
            tex_path,
            log_path,
            None,
            (),
            reason,
        )
    command = _compile_command(engine, tex_path)
    try:
        completed = subprocess.run(
            command,
            cwd=template_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(str(exc), encoding="utf-8")
        return _compatibility_result(
            template,
            LatexTemplateCompatibilityStatus.FAILED,
            tex_path,
            log_path,
            None,
            tuple(command),
            f"compile timed out after {timeout_seconds}s",
        )
    log_path.write_text(
        "STDOUT:\n" + completed.stdout + "\nSTDERR:\n" + completed.stderr,
        encoding="utf-8",
    )
    pdf_path = tex_path.with_suffix(".pdf")
    if completed.returncode == 0 and pdf_path.exists():
        return _compatibility_result(
            template,
            LatexTemplateCompatibilityStatus.COMPILED,
            tex_path,
            log_path,
            pdf_path,
            tuple(command),
            None,
        )
    return _compatibility_result(
        template,
        LatexTemplateCompatibilityStatus.FAILED,
        tex_path,
        log_path,
        None,
        tuple(command),
        f"LaTeX compile failed with exit code {completed.returncode}",
    )


def _compatibility_result(
    template: LatexTemplateSpec,
    status: LatexTemplateCompatibilityStatus,
    tex_path: Path,
    log_path: Path,
    pdf_path: Path | None,
    command: tuple[str, ...],
    reason: str | None,
) -> LatexTemplateCompatibilityResult:
    engine = Path(command[0]).name if command else None
    return LatexTemplateCompatibilityResult(
        template=template,
        status=status,
        tex_path=tex_path.as_posix(),
        pdf_path=pdf_path.as_posix() if pdf_path is not None else None,
        log_path=log_path.as_posix(),
        engine=engine,
        command=command,
        reason=reason,
    )


def _render_compatibility_markdown(
    report: LatexTemplateCompatibilityReport,
) -> str:
    lines = [
        "# LaTeX Template Compatibility",
        "",
        f"- Generated at: `{report.generated_at}`",
        f"- Output directory: `{report.output_dir}`",
        f"- JSON: `{report.json_path}`",
        f"- Vault copy: `{report.vault_markdown_path or 'not written'}`",
        "",
        "## Policy",
        "",
        "- Process data, run summaries, and evidence notes remain Markdown in the Obsidian vault.",
        "- Final paper-level delivery requires a template-specific LaTeX build that produces a PDF.",
        "",
        "## Results",
        "",
        "| Template | Source kind | Status | Engine | PDF | Log | Reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in report.results:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{result.template.id}`",
                    f"`{result.template.source_kind.value}`",
                    f"`{result.status.value}`",
                    f"`{result.engine or 'none'}`",
                    f"`{result.pdf_path or 'none'}`",
                    f"`{result.log_path}`",
                    _table_escape(result.reason or "None"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _write_vault_markdown(
    markdown: str,
    vault_root: Path | str | None,
    project_id: str | None,
) -> Path | None:
    if vault_root is None or not project_id:
        return None
    target = Path(vault_root) / "projects" / project_id / "paper" / "latex-template-compatibility.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target


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


def _table_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
