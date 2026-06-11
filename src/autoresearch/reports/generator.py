"""Generate MVP Markdown research reports from validated evidence."""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from pathlib import Path

from autoresearch.experiments import ValidationReport, require_evidence_for_metrics
from autoresearch.schemas import EvidenceEdge, ExecutionRun, ResultBundle


@dataclass(frozen=True)
class ReportContext:
    """Inputs required to render an evidence-backed research report."""

    title: str
    question: str
    literature_summary: str
    hypothesis: str
    experiment_design: str
    run: ExecutionRun
    results: ResultBundle
    validation: ValidationReport
    evidence_edges: list[EvidenceEdge]
    reproduction_command: str = "not recorded"
    python_version: str = field(default_factory=platform.python_version)
    dependency_lock_status: str = "not recorded"
    limitations: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def generate_markdown_report(
    context: ReportContext,
    *,
    output_path: Path | str | None = None,
) -> str:
    """Generate and optionally store an MVP Markdown research report."""

    require_evidence_for_metrics(context.results, context.evidence_edges)
    markdown = _render_markdown(context)
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
    return markdown


def _render_markdown(context: ReportContext) -> str:
    sections = [
        f"# {context.title}",
        "",
        "## Question",
        "",
        context.question,
        "",
        "## Literature Summary",
        "",
        context.literature_summary,
        "",
        "## Hypothesis",
        "",
        context.hypothesis,
        "",
        "## Experiment Design",
        "",
        context.experiment_design,
        "",
        "## Run Metadata",
        "",
        *_run_metadata_lines(context.run),
        "",
        "## Reproducibility",
        "",
        *_reproducibility_lines(context),
        "",
        "## Results",
        "",
        *_result_lines(context),
        "",
        "## Validation",
        "",
        *_validation_lines(context.validation),
        "",
        "## Limitations",
        "",
        *_bullet_lines(context.limitations),
        "",
        "## Next Steps",
        "",
        *_bullet_lines(context.next_steps),
        "",
    ]
    return "\n".join(sections)


def _run_metadata_lines(run: ExecutionRun) -> list[str]:
    return [
        f"- Run ID: `{run.id}`",
        f"- Task ID: `{run.task_id}`",
        f"- Status: `{run.status.value}`",
    ]


def _reproducibility_lines(context: ReportContext) -> list[str]:
    run = context.run
    return [
        f"- Command: `{context.reproduction_command}`",
        f"- Python version: `{context.python_version}`",
        f"- Dependency lock: `{context.dependency_lock_status}`",
        f"- Run ID: `{run.id}`",
        f"- Commit SHA: `{run.commit_sha or 'unknown'}`",
        f"- Config hash: `{run.config_hash or 'missing'}`",
        f"- Data hash: `{run.data_hash or 'missing'}`",
    ]


def _result_lines(context: ReportContext) -> list[str]:
    if not context.results.metrics:
        return ["- No quantitative metrics were collected."]
    evidence_by_metric = {
        edge.metric_name: edge
        for edge in context.evidence_edges
        if edge.metric_name is not None and edge.source_run_id == context.results.run_id
    }
    lines: list[str] = []
    for metric_name, value in sorted(context.results.metrics.items()):
        edge = evidence_by_metric[metric_name]
        lines.append(
            f"- `{metric_name}` = `{value}` "
            f"([evidence `{edge.id}`]({edge.source_artifact}))"
        )
    return lines


def _validation_lines(validation: ValidationReport) -> list[str]:
    lines = [f"- Validation status: `{validation.status.value}`"]
    if not validation.issues:
        lines.append("- No validation issues.")
        return lines
    lines.extend(
        f"- `{issue.severity.value}` `{issue.check}`: {issue.message}"
        for issue in validation.issues
    )
    return lines


def _bullet_lines(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
