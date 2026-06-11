"""Research report generation helpers."""

from .figures import FigureArtifact, FigureGenerationError, generate_metric_bar_figure
from .generator import ReportContext, generate_markdown_report
from .lint import (
    ReportLintError,
    ReportLintIssue,
    assert_report_readable,
    lint_markdown_report,
)

__all__ = [
    "FigureArtifact",
    "FigureGenerationError",
    "ReportContext",
    "ReportLintError",
    "ReportLintIssue",
    "assert_report_readable",
    "generate_metric_bar_figure",
    "generate_markdown_report",
    "lint_markdown_report",
]
