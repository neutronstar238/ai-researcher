import shutil
from pathlib import Path

import pytest

from autoresearch.reports import (
    LatexPaperBuildStatus,
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
    assert artifact.tex_path is not None
    tex = Path(artifact.tex_path).read_text(encoding="utf-8")
    assert r"\title{Evidence-Bound Demo Paper}" in tex
    assert r"\section{Related Work}" in tex
    assert r"\section{References}" in tex
    assert artifact.vault_markdown_path is not None
    vault_summary = Path(artifact.vault_markdown_path).read_text(encoding="utf-8")
    assert "The paper-level artifact is the compiled LaTeX PDF" in vault_summary


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


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex is unavailable")
def test_build_latex_paper_from_markdown_compiles_pdf(tmp_path: Path) -> None:
    source = tmp_path / "report.md"
    source.write_text(_complete_markdown(), encoding="utf-8")

    artifact = build_latex_paper_from_markdown(source, tmp_path / "paper")

    assert artifact.status is LatexPaperBuildStatus.COMPILED
    assert artifact.pdf_path is not None
    assert Path(artifact.pdf_path).is_file()
