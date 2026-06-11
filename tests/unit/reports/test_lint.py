from pathlib import Path

import pytest

from autoresearch.reports import ReportLintError, assert_report_readable, lint_markdown_report


def test_report_lint_accepts_valid_generated_shape(tmp_path: Path) -> None:
    (tmp_path / "metrics.json").write_text("{}", encoding="utf-8")
    markdown = _valid_report()

    assert lint_markdown_report(markdown, base_dir=tmp_path) == []
    assert_report_readable(markdown, base_dir=tmp_path)


def test_report_lint_fails_on_broken_evidence_link(tmp_path: Path) -> None:
    issues = lint_markdown_report(_valid_report(), base_dir=tmp_path)

    assert "link_exists" in {issue.check for issue in issues}
    with pytest.raises(ReportLintError, match="link_exists"):
        assert_report_readable(_valid_report(), base_dir=tmp_path)


def test_report_lint_fails_on_heading_order() -> None:
    markdown = _valid_report().replace("## Question", "## Results", 1)

    issues = lint_markdown_report(markdown)

    assert "heading_order" in {issue.check for issue in issues}


def test_report_lint_fails_on_malformed_table() -> None:
    markdown = _valid_report() + "\n| A | B |\n| --- |\n| 1 | 2 |\n"

    issues = lint_markdown_report(markdown)

    assert "table_format" in {issue.check for issue in issues}


def test_report_lint_fails_on_missing_metric_evidence_reference() -> None:
    markdown = _valid_report().replace(
        "- `accuracy` = `0.9` ([evidence `evidence_accuracy`](metrics.json))",
        "- `accuracy` = `0.9`",
    )

    issues = lint_markdown_report(markdown)

    assert "evidence_reference" in {issue.check for issue in issues}


def _valid_report() -> str:
    return "\n".join(
        [
            "# Demo",
            "",
            "## Question",
            "",
            "Question.",
            "",
            "## Literature Summary",
            "",
            "Summary.",
            "",
            "## Hypothesis",
            "",
            "Hypothesis.",
            "",
            "## Experiment Design",
            "",
            "Design.",
            "",
            "## Run Metadata",
            "",
            "- Run ID: `run_001`",
            "",
            "## Results",
            "",
            "- `accuracy` = `0.9` ([evidence `evidence_accuracy`](metrics.json))",
            "",
            "## Validation",
            "",
            "- Validation status: `passed`",
            "",
            "## Limitations",
            "",
            "- None",
            "",
            "## Next Steps",
            "",
            "- None",
            "",
        ]
    )
