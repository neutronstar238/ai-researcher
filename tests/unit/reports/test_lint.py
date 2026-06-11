import json
from pathlib import Path

import pytest

from autoresearch.reports import ReportLintError, assert_report_readable, lint_markdown_report


def test_report_lint_accepts_valid_generated_shape(tmp_path: Path) -> None:
    _write_metrics(tmp_path)
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


def test_report_lint_catches_metric_value_mismatches_against_source_file(
    tmp_path: Path,
) -> None:
    _write_metrics(tmp_path)
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    (figures_dir / "accuracy.png").write_bytes(b"png")
    markdown = _valid_report().replace(
        "- `accuracy` = `0.9` ([evidence `evidence_accuracy`](metrics.json))",
        "- `accuracy` = `0.8` ([evidence `evidence_accuracy`](metrics.json))",
    )
    markdown += "\n".join(
        [
            "",
            "| Metric | Value | Evidence |",
            "| --- | ---: | --- |",
            "| accuracy | 0.7 | [evidence `evidence_accuracy`](metrics.json) |",
            "![accuracy=0.6](figures/accuracy.png) "
            "([evidence `evidence_accuracy`](metrics.json))",
        ]
    )

    issues = lint_markdown_report(markdown, base_dir=tmp_path)

    metric_issues = [issue for issue in issues if issue.check == "metric_consistency"]
    assert len(metric_issues) == 3
    assert all("accuracy" in issue.message for issue in metric_issues)


def _write_metrics(base_dir: Path) -> None:
    (base_dir / "metrics.json").write_text(
        json.dumps({"metrics": {"accuracy": 0.9}}),
        encoding="utf-8",
    )


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
            "## Reproducibility",
            "",
            "- Command: `python experiment.py --config config.yaml`",
            "- Python version: `3.13.13`",
            "- Dependency lock: `poetry.lock present`",
            "- Run ID: `run_001`",
            "- Commit SHA: `abc123`",
            "- Config hash: `config-hash`",
            "- Data hash: `data-hash`",
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
