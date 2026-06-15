import shutil
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
