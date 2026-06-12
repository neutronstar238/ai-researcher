"""Generate MVP Markdown research reports from validated evidence."""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from autoresearch.evidence import EvidenceCoverageError, EvidenceGraph
from autoresearch.schemas import EvidenceEdge, ExecutionRun, ResultBundle

if TYPE_CHECKING:
    from autoresearch.experiments.validation import ValidationReport


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
    evidence_graph: EvidenceGraph | None = None
    core_claim_ids: list[str] = field(default_factory=list)
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

    from autoresearch.experiments.evidence import require_evidence_for_metrics

    require_evidence_for_metrics(context.results, context.evidence_edges)
    _require_core_claim_coverage(context)
    markdown = _render_markdown(context)
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
    return markdown


def _require_core_claim_coverage(context: ReportContext) -> None:
    if not context.core_claim_ids:
        return
    if context.evidence_graph is None:
        msg = "core claims require an evidence graph: " + ", ".join(context.core_claim_ids)
        raise EvidenceCoverageError(msg)
    context.evidence_graph.require_core_claim_coverage(context.core_claim_ids)


def _render_markdown(context: ReportContext) -> str:
    sections = [
        f"# {context.title}",
        "",
        "## Abstract",
        "",
        *_abstract_lines(),
        "",
        "## Introduction",
        "",
        *_introduction_lines(context),
        "",
        "## Related Work",
        "",
        *_related_work_lines(context),
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
        "## Method",
        "",
        *_method_lines(context),
        "",
        "## Experiment Design",
        "",
        context.experiment_design,
        "",
        "## Experiments",
        "",
        *_experiments_intro_lines(),
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
        "## Conclusion",
        "",
        *_conclusion_lines(context),
        "",
        "## References",
        "",
        *_reference_lines(context),
        "",
        "## Next Steps",
        "",
        *_bullet_lines(context.next_steps),
        "",
    ]
    return "\n".join(sections)


def _abstract_lines() -> list[str]:
    return [
        (
            "This draft reports a validated AI-Researcher experiment and keeps "
            "quantitative conclusions bound to the evidence-linked Results "
            "section. It does not claim publication-level novelty or generality "
            "unless the separate publication audit and source coverage checks pass."
        ),
    ]


def _introduction_lines(context: ReportContext) -> list[str]:
    return [
        context.question,
        "",
        (
            "The goal is to make the research loop auditable: the report connects "
            "the research question, hypothesis, executable run metadata, validated "
            "metrics, limitations, and follow-up work without inventing unsupported "
            "findings."
        ),
    ]


def _related_work_lines(context: ReportContext) -> list[str]:
    return [
        context.literature_summary,
        "",
        (
            "This section is limited to the supplied source-backed literature "
            "summary. A submission-quality manuscript still requires the retrieval "
            "and citation validators to attach full bibliographic records."
        ),
    ]


def _method_lines(context: ReportContext) -> list[str]:
    return [
        context.experiment_design,
        "",
        (
            "The method description is restricted to the executed experiment "
            "configuration and reproducibility metadata below; unexecuted variants "
            "must remain future work."
        ),
    ]


def _experiments_intro_lines() -> list[str]:
    return [
        (
            "The following subsections preserve the run metadata, reproduction "
            "command, evidence-linked metrics, and validation output used by the "
            "audit gates."
        ),
    ]


def _conclusion_lines(context: ReportContext) -> list[str]:
    if context.results.metrics:
        return [
            (
                "The completed run produced evidence-linked metrics and a validation "
                "report. These results support only the bounded experimental claims "
                "listed in this report; broader novelty, robustness, and publication "
                "readiness remain subject to the publication audit."
            )
        ]
    return [
        (
            "No quantitative result was collected, so this draft cannot support an "
            "empirical claim beyond recording the attempted workflow."
        )
    ]


def _reference_lines(context: ReportContext) -> list[str]:
    lines = [
        "- Literature context: supplied summary above; full bibliographic records must be provided by the citation pipeline before submission.",
        f"- Validation report: `{context.validation.json_path}`",
    ]
    for edge in sorted(context.evidence_edges, key=lambda item: item.id):
        lines.append(f"- Evidence `{edge.id}`: `{edge.source_artifact}`")
    return lines


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
