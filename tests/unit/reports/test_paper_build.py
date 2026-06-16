import shutil
import subprocess
from pathlib import Path

import pytest

import autoresearch.reports.paper_build as paper_build
from autoresearch.reports import (
    LatexPaperBuildStatus,
    LatexTemplateDependencyResolution,
    LatexTemplateDependencyStatus,
    build_latex_paper_from_markdown,
)


def _complete_markdown() -> str:
    return """# Evidence-Bound Demo Paper

## Abstract
This abstract is copied from validated local report evidence.

## Introduction
The introduction states the problem without claiming unsupported novelty.

## Related Work
Related work remains source-backed by the literature stage.

## Method
The method section describes the executed workflow.

## Experiments
The experiments section links to scripts, data, and run metadata.

## Results
The results section reports only validated metrics.

## Limitations
The limitations section records remaining evidence gaps.

## Conclusion
The conclusion avoids publication-ready claims unless gates pass.

## References
- Evidence vault record.
"""


def test_build_latex_paper_from_markdown_writes_tex_and_vault_summary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "report.md"
    source.write_text(_complete_markdown(), encoding="utf-8")

    artifact = build_latex_paper_from_markdown(
        source,
        tmp_path / "paper",
        compile_pdf=False,
        vault_root=tmp_path / "vault",
        project_id="demo_project",
    )

    assert artifact.status is LatexPaperBuildStatus.RENDERED
    assert artifact.reason == "compile_pdf disabled"
    assert artifact.missing_sections == ()
    assert artifact.dependency_resolution.status is LatexTemplateDependencyStatus.NOT_REQUIRED
    assert artifact.quality.passed is False
    assert "page_count" in artifact.quality.failures
    assert "word_count" in artifact.quality.failures
    assert artifact.tex_path is not None
    tex = Path(artifact.tex_path).read_text(encoding="utf-8")
    assert r"\title{Evidence-Bound Demo Paper}" in tex
    assert r"\section{Related Work}" in tex
    assert r"\usepackage{graphicx}" in tex
    assert r"\begin{thebibliography}{99}" in tex
    assert r"\bibitem{ref-1} Evidence vault record." in tex
    assert artifact.vault_markdown_path is not None
    vault_summary = Path(artifact.vault_markdown_path).read_text(encoding="utf-8")
    assert "release-ready only when status is `compiled`" in vault_summary
    assert "Dependency recovery: `not_required`" in vault_summary
    assert "Thin manuscripts" in vault_summary
    assert "Missing source-backed figures" in vault_summary


def test_build_latex_paper_flags_pseudo_reference_labels(tmp_path: Path) -> None:
    source = tmp_path / "report.md"
    source.write_text(
        _complete_markdown().replace(
            "- Evidence vault record.",
            "- [Cycle summary] AI-Researcher cycle summary JSON for this run.\n"
            "- [source2026] Verified Prototype Source. doi:10.1234/verified.",
        ),
        encoding="utf-8",
    )

    artifact = build_latex_paper_from_markdown(
        source,
        tmp_path / "paper",
        compile_pdf=False,
    )

    tex = Path(artifact.tex_path).read_text(encoding="utf-8")
    assert r"\bibitem{source2026}" in tex
    assert "[Cycle summary]" not in tex
    assert artifact.quality.invalid_reference_label_count == 1
    assert "reference_format" in artifact.quality.failures


def test_build_latex_paper_from_markdown_blocks_missing_sections(
    tmp_path: Path,
) -> None:
    source = tmp_path / "report.md"
    source.write_text("# Thin Report\n\n## Abstract\nOnly one section.\n", encoding="utf-8")

    artifact = build_latex_paper_from_markdown(source, tmp_path / "paper")

    assert artifact.status is LatexPaperBuildStatus.MISSING_SECTIONS
    assert "Introduction" in artifact.missing_sections
    assert artifact.pdf_path is None
    assert artifact.reason is not None
    assert "missing required paper sections" in artifact.reason


def test_build_latex_paper_external_template_records_dependency_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_ensure_dependency(
        _: object,
        __: Path,
        *,
        timeout_seconds: int,
    ) -> LatexTemplateDependencyResolution:
        assert timeout_seconds > 0
        return LatexTemplateDependencyResolution(
            status=LatexTemplateDependencyStatus.UNAVAILABLE,
            checked_at="2026-06-13T00:00:00+00:00",
            class_file="sn-jnl.cls",
            message="automatic LaTeX dependency recovery failed for sn-jnl.cls",
        )

    monkeypatch.setattr(
        paper_build,
        "ensure_latex_template_class_available",
        fake_ensure_dependency,
    )
    source = tmp_path / "report.md"
    source.write_text(_complete_markdown(), encoding="utf-8")

    artifact = build_latex_paper_from_markdown(
        source,
        tmp_path / "paper",
        template_id="springer-nature-sn-jnl",
    )

    assert artifact.status is LatexPaperBuildStatus.SOURCE_UNAVAILABLE
    assert artifact.dependency_resolution.status is LatexTemplateDependencyStatus.UNAVAILABLE
    assert artifact.reason == "automatic LaTeX dependency recovery failed for sn-jnl.cls"
    summary = Path(artifact.markdown_path).read_text(encoding="utf-8")
    assert "Dependency recovery: `unavailable`" in summary


def test_compile_latex_reruns_when_cross_references_need_second_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tex_path = tmp_path / "main.tex"
    log_path = tmp_path / "compile.log"
    tex_path.write_text(r"\documentclass{article}\begin{document}x\end{document}", encoding="utf-8")
    calls: list[int] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(len(calls) + 1)
        assert command == ["pdflatex", "main.tex"]
        assert kwargs["cwd"] == tmp_path
        tex_path.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
        stdout = (
            "LaTeX Warning: Label(s) may have changed. "
            "Rerun to get cross-references right.\n"
            if len(calls) == 1
            else "Output written on main.pdf.\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(paper_build.subprocess, "run", fake_run)

    status, pdf_path, reason = paper_build._compile_latex(
        tex_path,
        log_path,
        ["pdflatex", "main.tex"],
        timeout_seconds=5,
    )

    assert status is LatexPaperBuildStatus.COMPILED
    assert pdf_path == tex_path.with_suffix(".pdf")
    assert reason is None
    assert calls == [1, 2]
    log_text = log_path.read_text(encoding="utf-8")
    assert "RERUNS_COMPLETED: 1" in log_text
    assert "ATTEMPT 1" not in log_text
    assert "ATTEMPT 2" in log_text
    assert "Rerun to get cross-references right" not in log_text


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex is unavailable")
def test_build_latex_paper_from_markdown_compiles_pdf(tmp_path: Path) -> None:
    source = tmp_path / "report.md"
    source.write_text(_complete_markdown(), encoding="utf-8")

    artifact = build_latex_paper_from_markdown(source, tmp_path / "paper")

    assert artifact.status is LatexPaperBuildStatus.COMPILED_WITH_QUALITY_ISSUES
    assert artifact.pdf_path is not None
    assert Path(artifact.pdf_path).is_file()
    assert artifact.quality.passed is False
    assert "page_count" in artifact.quality.failures
    assert "word_count" in artifact.quality.failures
