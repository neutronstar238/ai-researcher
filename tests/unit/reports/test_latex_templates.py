import shutil
from pathlib import Path

import pytest

import autoresearch.reports.latex_templates as latex_templates
from autoresearch.reports import (
    LatexTemplateCompatibilityStatus,
    LatexTemplateSourceFetchStatus,
    LatexTemplateSourceKind,
    LatexTemplateSourceMetadata,
    external_latex_templates,
    generic_latex_templates,
    render_latex_template_smoke,
    run_latex_template_compatibility,
)


def test_generic_latex_templates_include_single_and_double_column() -> None:
    templates = generic_latex_templates()

    assert [template.id for template in templates] == [
        "generic-article-one-column",
        "generic-article-two-column",
    ]
    assert all(template.source_kind is LatexTemplateSourceKind.BUILT_IN_GENERIC for template in templates)
    assert templates[0].class_options == ("11pt",)
    assert templates[1].class_options == ("11pt", "twocolumn")


def test_render_latex_template_smoke_has_required_paper_sections() -> None:
    template = generic_latex_templates()[1]

    tex = render_latex_template_smoke(template)

    assert r"\documentclass[11pt,twocolumn]{article}" in tex
    assert r"\begin{abstract}" in tex
    for section in [
        "Introduction",
        "Related Work",
        "Method",
        "Experiments",
        "Results",
        "Limitations",
        "Conclusion",
    ]:
        assert rf"\section{{{section}}}" in tex
    assert r"\begin{thebibliography}{1}" in tex


def test_external_latex_templates_record_source_urls_and_license_boundaries() -> None:
    templates = external_latex_templates()

    assert [template.id for template in templates] == [
        "ieee-ieeetran-conference",
        "acm-acmart-sigconf",
        "springer-nature-sn-jnl",
    ]
    assert all(template.source_kind is LatexTemplateSourceKind.EXTERNAL_FETCHED for template in templates)
    assert all(template.source_url for template in templates)
    assert all("not vendored" in template.license_note for template in templates)
    assert external_latex_templates()[1].preamble_lines


def test_run_latex_template_compatibility_can_skip_compile_and_write_vault_markdown(
    tmp_path: Path,
) -> None:
    report = run_latex_template_compatibility(
        tmp_path / "compat",
        compile_pdf=False,
        vault_root=tmp_path / "vault",
        project_id="project_1",
    )

    assert Path(report.json_path).is_file()
    assert Path(report.markdown_path).is_file()
    assert report.vault_markdown_path is not None
    assert Path(report.vault_markdown_path).is_file()
    assert {result.status for result in report.results} == {
        LatexTemplateCompatibilityStatus.SKIPPED
    }
    assert all(result.reason == "compile_pdf disabled" for result in report.results)
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")
    vault_markdown = Path(report.vault_markdown_path).read_text(encoding="utf-8")
    assert "Final paper-level delivery requires a template-specific LaTeX build" in markdown
    assert "Vault copy: `not written`" not in vault_markdown
    assert "latex-template-compatibility.md" in vault_markdown


def test_run_latex_template_compatibility_skips_when_engine_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(latex_templates, "_select_latex_engine", lambda: None)

    report = run_latex_template_compatibility(tmp_path / "compat")

    assert {result.status for result in report.results} == {
        LatexTemplateCompatibilityStatus.SKIPPED
    }
    assert all(result.reason == "no LaTeX engine found on PATH" for result in report.results)


def test_run_latex_template_compatibility_marks_missing_external_class_source_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(latex_templates, "_template_class_available", lambda _: False)

    report = run_latex_template_compatibility(
        tmp_path / "compat",
        templates=(external_latex_templates()[2],),
    )

    [result] = report.results
    assert result.status is LatexTemplateCompatibilityStatus.SOURCE_UNAVAILABLE
    assert result.reason == "template class sn-jnl.cls is unavailable"


def test_run_latex_template_compatibility_records_fetched_source_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_source_metadata(
        _: object,
        cache_dir: Path,
        *,
        timeout_seconds: int,
    ) -> LatexTemplateSourceMetadata:
        assert timeout_seconds > 0
        return LatexTemplateSourceMetadata(
            status=LatexTemplateSourceFetchStatus.FETCHED,
            checked_at="2026-06-13T00:00:00+00:00",
            http_status=200,
            cache_path=(cache_dir / "source.json").as_posix(),
        )

    monkeypatch.setattr(latex_templates, "_template_class_available", lambda _: True)
    monkeypatch.setattr(
        latex_templates,
        "_fetch_template_source_metadata",
        fake_fetch_source_metadata,
    )

    report = run_latex_template_compatibility(
        tmp_path / "compat",
        templates=(external_latex_templates()[0],),
        compile_pdf=False,
        fetch_sources=True,
        source_fetch_interval_seconds=0,
    )

    [result] = report.results
    assert result.source_metadata.status is LatexTemplateSourceFetchStatus.FETCHED
    assert result.source_metadata.http_status == 200
    assert result.source_metadata.checked_at == "2026-06-13T00:00:00+00:00"
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")
    assert "`fetched`<br>`2026-06-13T00:00:00+00:00`" in markdown
    assert "`200`" in markdown


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex is unavailable")
def test_run_latex_template_compatibility_compiles_generic_templates(
    tmp_path: Path,
) -> None:
    report = run_latex_template_compatibility(tmp_path / "compat")

    assert {result.status for result in report.results} == {
        LatexTemplateCompatibilityStatus.COMPILED
    }
    for result in report.results:
        assert result.pdf_path is not None
        assert Path(result.pdf_path).is_file()
        assert Path(result.log_path).is_file()


@pytest.mark.skipif(
    shutil.which("pdflatex") is None or shutil.which("kpsewhich") is None,
    reason="pdflatex/kpsewhich is unavailable",
)
def test_run_latex_template_compatibility_compiles_available_external_templates(
    tmp_path: Path,
) -> None:
    templates = external_latex_templates()[:2]
    report = run_latex_template_compatibility(tmp_path / "compat", templates=templates)

    assert {result.status for result in report.results} == {
        LatexTemplateCompatibilityStatus.COMPILED
    }
    assert all(result.pdf_path and Path(result.pdf_path).is_file() for result in report.results)
