"""Research report generation helpers."""

from .citations import (
    BibtexArtifact,
    CitationGenerationError,
    CitationStatus,
    CitationValidation,
    generate_bibtex,
    validate_citations,
)
from .figures import FigureArtifact, FigureGenerationError, generate_metric_bar_figure
from .generator import ReportContext, generate_markdown_report
from .latex import (
    LatexCompilationError,
    LatexDraftArtifact,
    LatexDraftContext,
    LatexGenerationError,
    generate_latex_skeleton,
)
from .lint import (
    ReportLintError,
    ReportLintIssue,
    assert_metric_consistency,
    assert_report_readable,
    lint_markdown_report,
    lint_metric_consistency,
)
from .tables import (
    MetricsTableArtifact,
    MetricsTableInput,
    TableGenerationError,
    generate_ablation_table,
    generate_method_comparison_table,
)

__all__ = [
    "BibtexArtifact",
    "CitationGenerationError",
    "CitationStatus",
    "CitationValidation",
    "FigureArtifact",
    "FigureGenerationError",
    "LatexCompilationError",
    "LatexDraftArtifact",
    "LatexDraftContext",
    "LatexGenerationError",
    "MetricsTableArtifact",
    "MetricsTableInput",
    "ReportContext",
    "ReportLintError",
    "ReportLintIssue",
    "TableGenerationError",
    "assert_metric_consistency",
    "assert_report_readable",
    "generate_bibtex",
    "generate_ablation_table",
    "generate_metric_bar_figure",
    "generate_method_comparison_table",
    "generate_latex_skeleton",
    "lint_metric_consistency",
    "generate_markdown_report",
    "lint_markdown_report",
    "validate_citations",
]
