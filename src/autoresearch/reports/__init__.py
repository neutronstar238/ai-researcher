"""Research report generation helpers."""

from .figures import FigureArtifact, FigureGenerationError, generate_metric_bar_figure
from .generator import ReportContext, generate_markdown_report
from .lint import (
    ReportLintError,
    ReportLintIssue,
    assert_report_readable,
    lint_markdown_report,
)
from .tables import (
    MetricsTableArtifact,
    MetricsTableInput,
    TableGenerationError,
    generate_ablation_table,
    generate_method_comparison_table,
)

__all__ = [
    "FigureArtifact",
    "FigureGenerationError",
    "MetricsTableArtifact",
    "MetricsTableInput",
    "ReportContext",
    "ReportLintError",
    "ReportLintIssue",
    "TableGenerationError",
    "assert_report_readable",
    "generate_ablation_table",
    "generate_metric_bar_figure",
    "generate_method_comparison_table",
    "generate_markdown_report",
    "lint_markdown_report",
]
