"""LaTeX template compatibility smoke tests for paper delivery."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
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
    SOURCE_UNAVAILABLE = "source_unavailable"
    FAILED = "failed"


class LatexTemplateSourceFetchStatus(str, Enum):
    """Source metadata fetch outcome for external templates."""

    BUILT_IN = "built_in"
    NOT_REQUESTED = "not_requested"
    FETCHED = "fetched"
    CACHED = "cached"
    FAILED = "failed"


class LatexTemplateDependencyStatus(str, Enum):
    """Dependency recovery outcome for a LaTeX template class."""

    NOT_REQUIRED = "not_required"
    AVAILABLE = "available"
    INSTALLED = "installed"
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LatexTemplateSpec:
    """One LaTeX paper template target."""

    id: str
    display_name: str
    source_kind: LatexTemplateSourceKind
    document_class: str
    class_options: tuple[str, ...] = ()
    class_file: str | None = None
    preamble_lines: tuple[str, ...] = ()
    abstract_before_maketitle: bool = False
    source_url: str | None = None
    texlive_package: str | None = None
    source_archive_url: str | None = None
    source_archive_member: str | None = None
    license_note: str = "Built-in generic LaTeX article smoke template."

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "source_kind": self.source_kind.value,
            "document_class": self.document_class,
            "class_options": list(self.class_options),
            "class_file": self.class_file,
            "preamble_lines": list(self.preamble_lines),
            "abstract_before_maketitle": self.abstract_before_maketitle,
            "source_url": self.source_url,
            "texlive_package": self.texlive_package,
            "source_archive_url": self.source_archive_url,
            "source_archive_member": self.source_archive_member,
            "license_note": self.license_note,
        }


@dataclass(frozen=True)
class LatexTemplateSourceMetadata:
    """Source metadata evidence for one template check."""

    status: LatexTemplateSourceFetchStatus
    checked_at: str | None = None
    http_status: int | None = None
    cache_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checked_at": self.checked_at,
            "http_status": self.http_status,
            "cache_path": self.cache_path,
            "error": self.error,
        }


@dataclass(frozen=True)
class LatexTemplateDependencyResolution:
    """Structured record of a template dependency check or recovery attempt."""

    status: LatexTemplateDependencyStatus
    checked_at: str
    class_file: str | None
    message: str
    command: tuple[str, ...] = ()
    returncode: int | None = None
    artifact_path: str | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checked_at": self.checked_at,
            "class_file": self.class_file,
            "message": self.message,
            "command": list(self.command),
            "returncode": self.returncode,
            "artifact_path": self.artifact_path,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "error": self.error,
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
    source_metadata: LatexTemplateSourceMetadata
    dependency_resolution: LatexTemplateDependencyResolution
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
            "source_metadata": self.source_metadata.to_dict(),
            "dependency_resolution": self.dependency_resolution.to_dict(),
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


def external_latex_templates() -> tuple[LatexTemplateSpec, ...]:
    """Return external venue/publisher template targets for compatibility checks."""

    return (
        LatexTemplateSpec(
            id="ieee-ieeetran-conference",
            display_name="IEEEtran Conference",
            source_kind=LatexTemplateSourceKind.EXTERNAL_FETCHED,
            document_class="IEEEtran",
            class_options=("conference",),
            class_file="IEEEtran.cls",
            source_url="https://ctan.org/pkg/IEEEtran",
            texlive_package="ieeetran",
            license_note="External IEEEtran class from CTAN/TeX distribution; not vendored by AI-Researcher.",
        ),
        LatexTemplateSpec(
            id="acm-acmart-sigconf",
            display_name="ACM acmart SIGCONF",
            source_kind=LatexTemplateSourceKind.EXTERNAL_FETCHED,
            document_class="acmart",
            class_options=("sigconf", "nonacm"),
            class_file="acmart.cls",
            preamble_lines=(
                r"\settopmatter{printacmref=false}",
                r"\setcopyright{none}",
                r"\acmConference[AI-Researcher Smoke]{AI-Researcher Smoke}{2026}{Local}",
                r"\acmYear{2026}",
            ),
            abstract_before_maketitle=True,
            source_url="https://ctan.org/pkg/acmart",
            texlive_package="acmart",
            license_note="External ACM acmart class from CTAN/TeX distribution; not vendored by AI-Researcher.",
        ),
        LatexTemplateSpec(
            id="springer-nature-sn-jnl",
            display_name="Springer Nature sn-jnl",
            source_kind=LatexTemplateSourceKind.EXTERNAL_FETCHED,
            document_class="sn-jnl",
            class_options=("sn-mathphys",),
            class_file="sn-jnl.cls",
            preamble_lines=(r"\usepackage{amsmath}",),
            source_url="https://www.springernature.com/gp/authors/campaigns/latex-author-support",
            source_archive_url=(
                "https://cms-resources.apps.public.k8s.springernature.io/"
                "springer-cms/rest/v1/content/18782940/data/v12"
            ),
            source_archive_member="sn-jnl.cls",
            license_note="External Springer Nature authoring template; not vendored by AI-Researcher.",
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
    fetch_sources: bool = False,
    source_cache_dir: Path | str | None = None,
    source_fetch_interval_seconds: float = 1.0,
    source_fetch_timeout_seconds: int = 15,
) -> LatexTemplateCompatibilityReport:
    """Render and optionally compile smoke manuscripts for LaTeX templates."""

    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected_templates = templates or generic_latex_templates()
    source_cache = Path(source_cache_dir).resolve() if source_cache_dir else root / "source-cache"
    results_list: list[LatexTemplateCompatibilityResult] = []
    fetched_any_source = False
    for template in selected_templates:
        source_metadata = _default_source_metadata(template)
        if fetch_sources and template.source_kind is LatexTemplateSourceKind.EXTERNAL_FETCHED:
            if fetched_any_source and source_fetch_interval_seconds > 0:
                time.sleep(source_fetch_interval_seconds)
            source_metadata = _fetch_template_source_metadata(
                template,
                source_cache,
                timeout_seconds=source_fetch_timeout_seconds,
            )
            fetched_any_source = True
        results_list.append(
            _run_template_smoke(
                root,
                template,
                compile_pdf=compile_pdf,
                timeout_seconds=timeout_seconds,
                source_metadata=source_metadata,
            )
        )
    results = tuple(results_list)
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
        *template.preamble_lines,
        r"\begin{document}",
    ]
    abstract_lines = [
        r"\begin{abstract}",
        (
            "This generated manuscript verifies that AI-Researcher can move from "
            "an Obsidian-readable evidence draft to a LaTeX template artifact."
        ),
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


def ensure_latex_template_class_available(
    template: LatexTemplateSpec,
    work_dir: Path | str,
    *,
    timeout_seconds: int = 120,
) -> LatexTemplateDependencyResolution:
    """Ensure an external template class is available, recording every recovery path."""

    checked_at = datetime.now(timezone.utc).isoformat()
    class_file = template.class_file or f"{template.document_class}.cls"
    if template.source_kind is LatexTemplateSourceKind.BUILT_IN_GENERIC:
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.NOT_REQUIRED,
            checked_at=checked_at,
            class_file=class_file,
            message="built-in generic templates do not require external class recovery",
        )

    root = Path(work_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    local_class = root / class_file
    if local_class.exists():
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.AVAILABLE,
            checked_at=checked_at,
            class_file=class_file,
            message="template class already exists in the build directory",
            artifact_path=local_class.as_posix(),
        )
    if _template_class_available(template):
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.AVAILABLE,
            checked_at=checked_at,
            class_file=class_file,
            message="template class is available through kpsewhich",
        )

    recovery_notes: list[str] = []
    install_result = _try_texlive_package_install(
        template,
        checked_at=checked_at,
        timeout_seconds=timeout_seconds,
    )
    if install_result is not None:
        if _template_class_available(template):
            return install_result
        recovery_notes.append(install_result.message)

    archive_result = _try_source_archive_download(
        template,
        root,
        checked_at=checked_at,
        timeout_seconds=timeout_seconds,
    )
    if archive_result is not None:
        if archive_result.status is LatexTemplateDependencyStatus.DOWNLOADED:
            return archive_result
        recovery_notes.append(archive_result.message)

    if not template.texlive_package:
        recovery_notes.append("no TeX Live package is configured")
    if not template.source_archive_url:
        recovery_notes.append("no official source archive URL is configured")
    return LatexTemplateDependencyResolution(
        status=LatexTemplateDependencyStatus.UNAVAILABLE,
        checked_at=checked_at,
        class_file=class_file,
        message=(
            f"automatic LaTeX dependency recovery failed for {class_file}: "
            + "; ".join(dict.fromkeys(recovery_notes))
        ),
    )


def _run_template_smoke(
    root: Path,
    template: LatexTemplateSpec,
    *,
    compile_pdf: bool,
    timeout_seconds: int,
    source_metadata: LatexTemplateSourceMetadata,
) -> LatexTemplateCompatibilityResult:
    template_dir = root / template.id
    template_dir.mkdir(parents=True, exist_ok=True)
    tex_path = template_dir / "main.tex"
    log_path = template_dir / "compile.log"
    tex_path.write_text(render_latex_template_smoke(template), encoding="utf-8")
    dependency_resolution = _default_dependency_resolution(template, "compile_pdf disabled")
    if source_metadata.status is LatexTemplateSourceFetchStatus.FAILED:
        reason = f"source metadata fetch failed: {source_metadata.error}"
        log_path.write_text(reason + "\n", encoding="utf-8")
        return _compatibility_result(
            template,
            LatexTemplateCompatibilityStatus.SOURCE_UNAVAILABLE,
            tex_path,
            log_path,
            None,
            (),
            source_metadata,
            dependency_resolution,
            reason,
        )
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
            source_metadata,
            dependency_resolution,
            reason,
        )
    dependency_resolution = ensure_latex_template_class_available(
        template,
        template_dir,
        timeout_seconds=timeout_seconds,
    )
    if dependency_resolution.status is LatexTemplateDependencyStatus.UNAVAILABLE:
        reason = dependency_resolution.message
        log_path.write_text(reason + "\n", encoding="utf-8")
        return _compatibility_result(
            template,
            LatexTemplateCompatibilityStatus.SOURCE_UNAVAILABLE,
            tex_path,
            log_path,
            None,
            (),
            source_metadata,
            dependency_resolution,
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
            source_metadata,
            dependency_resolution,
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
            source_metadata,
            dependency_resolution,
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
            source_metadata,
            dependency_resolution,
            None,
        )
    return _compatibility_result(
        template,
        LatexTemplateCompatibilityStatus.FAILED,
        tex_path,
        log_path,
        None,
        tuple(command),
        source_metadata,
        dependency_resolution,
        f"LaTeX compile failed with exit code {completed.returncode}",
    )


def _compatibility_result(
    template: LatexTemplateSpec,
    status: LatexTemplateCompatibilityStatus,
    tex_path: Path,
    log_path: Path,
    pdf_path: Path | None,
    command: tuple[str, ...],
    source_metadata: LatexTemplateSourceMetadata,
    dependency_resolution: LatexTemplateDependencyResolution,
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
        source_metadata=source_metadata,
        dependency_resolution=dependency_resolution,
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
        "| Template | Source kind | Source | Source check | Dependency | HTTP | Status | Engine | PDF | Log | Reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in report.results:
        dependency_cell = f"`{result.dependency_resolution.status.value}`"
        if result.dependency_resolution.message:
            dependency_cell += f"<br>{_table_escape(result.dependency_resolution.message)}"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{result.template.id}`",
                    f"`{result.template.source_kind.value}`",
                    f"`{result.template.source_url or 'built-in'}`",
                    f"`{result.source_metadata.status.value}`"
                    + (
                        f"<br>`{result.source_metadata.checked_at}`"
                        if result.source_metadata.checked_at
                        else ""
                    ),
                    dependency_cell,
                    f"`{result.source_metadata.http_status or 'n/a'}`",
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


def _default_source_metadata(template: LatexTemplateSpec) -> LatexTemplateSourceMetadata:
    if template.source_kind is LatexTemplateSourceKind.BUILT_IN_GENERIC:
        return LatexTemplateSourceMetadata(status=LatexTemplateSourceFetchStatus.BUILT_IN)
    return LatexTemplateSourceMetadata(status=LatexTemplateSourceFetchStatus.NOT_REQUESTED)


def _fetch_template_source_metadata(
    template: LatexTemplateSpec,
    cache_dir: Path,
    *,
    timeout_seconds: int,
) -> LatexTemplateSourceMetadata:
    checked_at = datetime.now(timezone.utc).isoformat()
    if not template.source_url:
        return LatexTemplateSourceMetadata(
            status=LatexTemplateSourceFetchStatus.FAILED,
            checked_at=checked_at,
            error="template source URL is not configured",
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(template.source_url.encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{cache_key}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return LatexTemplateSourceMetadata(
            status=LatexTemplateSourceFetchStatus.CACHED,
            checked_at=checked_at,
            http_status=cached.get("http_status"),
            cache_path=cache_path.as_posix(),
        )
    request = urllib.request.Request(
        template.source_url,
        headers={"User-Agent": "AI-Researcher template-compatibility-check/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(65536)
            http_status = response.getcode()
            metadata = {
                "url": template.source_url,
                "final_url": response.geturl(),
                "http_status": http_status,
                "fetched_at": checked_at,
                "sample_sha256": hashlib.sha256(payload).hexdigest(),
                "sample_bytes": len(payload),
            }
    except urllib.error.HTTPError as exc:
        return LatexTemplateSourceMetadata(
            status=LatexTemplateSourceFetchStatus.FAILED,
            checked_at=checked_at,
            http_status=exc.code,
            error=str(exc),
        )
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return LatexTemplateSourceMetadata(
            status=LatexTemplateSourceFetchStatus.FAILED,
            checked_at=checked_at,
            error=str(exc),
        )
    cache_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return LatexTemplateSourceMetadata(
        status=LatexTemplateSourceFetchStatus.FETCHED,
        checked_at=checked_at,
        http_status=http_status,
        cache_path=cache_path.as_posix(),
    )


def _default_dependency_resolution(
    template: LatexTemplateSpec,
    message: str,
) -> LatexTemplateDependencyResolution:
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
        message=message,
    )


def _try_texlive_package_install(
    template: LatexTemplateSpec,
    *,
    checked_at: str,
    timeout_seconds: int,
) -> LatexTemplateDependencyResolution | None:
    if not template.texlive_package:
        return None
    class_file = template.class_file or f"{template.document_class}.cls"
    tlmgr = shutil.which("tlmgr") or shutil.which("tlmgr.bat")
    if tlmgr is None:
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.UNAVAILABLE,
            checked_at=checked_at,
            class_file=class_file,
            message=f"tlmgr is not on PATH; cannot install TeX Live package {template.texlive_package}",
        )
    command = [tlmgr, "install", template.texlive_package]
    if Path(tlmgr).suffix.casefold() in {".bat", ".cmd"}:
        command = ["cmd", "/c", tlmgr, "install", template.texlive_package]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.UNAVAILABLE,
            checked_at=checked_at,
            class_file=class_file,
            message=(
                f"tlmgr install {template.texlive_package} timed out after "
                f"{timeout_seconds}s"
            ),
            command=tuple(command),
            stdout_tail=_tail_text(exc.stdout),
            stderr_tail=_tail_text(exc.stderr),
            error=str(exc),
        )
    except OSError as exc:
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.UNAVAILABLE,
            checked_at=checked_at,
            class_file=class_file,
            message=f"tlmgr install {template.texlive_package} could not start: {exc}",
            command=tuple(command),
            error=str(exc),
        )
    status = (
        LatexTemplateDependencyStatus.INSTALLED
        if completed.returncode == 0
        else LatexTemplateDependencyStatus.UNAVAILABLE
    )
    message = (
        f"tlmgr install {template.texlive_package} completed; kpsewhich will verify {class_file}"
        if completed.returncode == 0
        else f"tlmgr install {template.texlive_package} failed with exit code {completed.returncode}"
    )
    return LatexTemplateDependencyResolution(
        status=status,
        checked_at=checked_at,
        class_file=class_file,
        message=message,
        command=tuple(command),
        returncode=completed.returncode,
        stdout_tail=_tail_text(completed.stdout),
        stderr_tail=_tail_text(completed.stderr),
    )


def _try_source_archive_download(
    template: LatexTemplateSpec,
    work_dir: Path,
    *,
    checked_at: str,
    timeout_seconds: int,
) -> LatexTemplateDependencyResolution | None:
    if not template.source_archive_url:
        return None
    class_file = template.class_file or f"{template.document_class}.cls"
    archive_dir = work_dir / "template-source"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{_safe_filename(template.id)}.zip"
    if not archive_path.exists():
        request = urllib.request.Request(
            template.source_archive_url,
            headers={"User-Agent": "AI-Researcher latex-dependency-recovery/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read(128 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            return LatexTemplateDependencyResolution(
                status=LatexTemplateDependencyStatus.UNAVAILABLE,
                checked_at=checked_at,
                class_file=class_file,
                message=f"official template archive returned HTTP {exc.code}",
                artifact_path=archive_path.as_posix(),
                error=str(exc),
            )
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            return LatexTemplateDependencyResolution(
                status=LatexTemplateDependencyStatus.UNAVAILABLE,
                checked_at=checked_at,
                class_file=class_file,
                message=f"official template archive download failed: {exc}",
                artifact_path=archive_path.as_posix(),
                error=str(exc),
            )
        if len(payload) > 128 * 1024 * 1024:
            return LatexTemplateDependencyResolution(
                status=LatexTemplateDependencyStatus.UNAVAILABLE,
                checked_at=checked_at,
                class_file=class_file,
                message="official template archive exceeded the 128 MiB recovery limit",
                artifact_path=archive_path.as_posix(),
            )
        archive_path.write_bytes(payload)
    wanted_member = (template.source_archive_member or class_file).replace("\\", "/")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            member = _find_archive_member(archive.namelist(), wanted_member)
            if member is None:
                return LatexTemplateDependencyResolution(
                    status=LatexTemplateDependencyStatus.UNAVAILABLE,
                    checked_at=checked_at,
                    class_file=class_file,
                    message=f"official template archive does not contain {wanted_member}",
                    artifact_path=archive_path.as_posix(),
                )
            target = work_dir / class_file
            target.write_bytes(archive.read(member))
    except (OSError, zipfile.BadZipFile) as exc:
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.UNAVAILABLE,
            checked_at=checked_at,
            class_file=class_file,
            message=f"official template archive could not be read: {exc}",
            artifact_path=archive_path.as_posix(),
            error=str(exc),
        )
    return LatexTemplateDependencyResolution(
        status=LatexTemplateDependencyStatus.DOWNLOADED,
        checked_at=checked_at,
        class_file=class_file,
        message=f"downloaded {class_file} from the official template archive",
        artifact_path=target.as_posix(),
    )


def _find_archive_member(members: list[str], wanted_member: str) -> str | None:
    for member in members:
        normalized = member.replace("\\", "/")
        if normalized == wanted_member or normalized.endswith(f"/{wanted_member}"):
            return member
    return None


def _tail_text(value: str | bytes | None, *, max_chars: int = 1200) -> str | None:
    if value is None:
        return None
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _safe_filename(value: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in value)
    return safe.strip("-") or "template"


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


def _table_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
